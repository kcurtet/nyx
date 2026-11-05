/**
 * jerga · voz de Trinity (extensión de pi).
 *
 * - Al empezar un turno (llega una orden nueva): `jerga hush`, calla lo que se estuviera leyendo.
 * - Al terminar: lee la respuesta final con `jerga say` (phonon + lexicón + normalizador).
 *   Respuestas largas: solo el principio y "el resto lo tienes en el panel".
 * - Si el modelo falla (cuota, auth, red): lo dice en una frase clara.
 *
 * Se carga solo en la sesión de Trinity (`jerga trinity` la arranca con -e).
 * Depuración: JERGA_VOICE_DEBUG=1 escribe los eventos en ~/.local/state/jerga/voice.log
 */
import { spawn } from "node:child_process";
import { appendFileSync, existsSync, mkdirSync } from "node:fs";
import os from "node:os";
import path from "node:path";

const MAX_SPOKEN = 420;

type Msg = { role?: string; content?: unknown; stopReason?: string; errorMessage?: string };

function debug(what: string): void {
	if (!process.env.JERGA_VOICE_DEBUG) return;
	try {
		const dir = path.join(os.homedir(), ".local", "state", "jerga");
		mkdirSync(dir, { recursive: true });
		appendFileSync(path.join(dir, "voice.log"), `${new Date().toISOString()} ${what}\n`);
	} catch {
		// sin log
	}
}

function jergaBin(): string {
	const env = process.env.JERGA_BIN;
	if (env) return env;
	const local = path.join(os.homedir(), ".local", "bin", "jerga");
	return existsSync(local) ? local : "jerga";
}

function run(args: string[], stdin?: string): void {
	try {
		const child = spawn(jergaBin(), args, { stdio: [stdin === undefined ? "ignore" : "pipe", "ignore", "ignore"] });
		child.on("error", (e) => debug(`spawn error: ${e}`));
		if (stdin !== undefined) child.stdin?.end(stdin);
	} catch (e) {
		debug(`spawn throw: ${e}`); // la voz nunca rompe el turno
	}
}

/** Error del modelo en palabras que se entiendan al oído (el original puede venir hasta en chino). */
export function spokenError(err: string): string {
	const e = err.toLowerCase();
	if (/\b429\b|rate.?limit|quota|limit|上限|限额/.test(e)) return "No puedo responder: has llegado al límite de uso del modelo.";
	if (/\b40[13]\b|auth|api key|unauthori[sz]ed|forbidden/.test(e)) return "No puedo responder: hay un problema de autenticación con el modelo.";
	if (/timeout|timed out|etimedout|econn|network|fetch failed|enotfound|\b50[234]\b|overloaded/.test(e))
		return "No puedo responder: no hay conexión con el modelo o está saturado. Prueba en un momento.";
	return "El modelo ha devuelto un error. Tienes el detalle en el panel.";
}

function textOf(m: Msg): string {
	if (typeof m.content === "string") return m.content;
	if (Array.isArray(m.content)) {
		return m.content
			.filter((c): c is { type: string; text: string } => typeof c === "object" && c !== null && (c as { type?: string }).type === "text")
			.map((c) => c.text)
			.join("");
	}
	return "";
}

/** Último mensaje del asistente: su texto, o el aviso de error si falló. */
export function answerOf(messages: Msg[] = []): string {
	for (let i = messages.length - 1; i >= 0; i--) {
		const m = messages[i]!;
		if (m.role !== "assistant") continue;
		if (m.stopReason === "error") return spokenError(m.errorMessage ?? "");
		return textOf(m);
	}
	return "";
}

/** Recorta por frases a ~MAX_SPOKEN caracteres. */
export function spoken(answer: string): string {
	const text = answer.trim();
	if (text.length <= MAX_SPOKEN) return text;
	const sentences = text.match(/[^.!?¿¡\n]+[.!?]*/g) ?? [text];
	let out = "";
	for (const s of sentences) {
		if ((out + s).length > MAX_SPOKEN) break;
		out += s;
	}
	return `${(out || text.slice(0, MAX_SPOKEN)).trim()} El resto lo tienes en el panel.`;
}

// El tipo ExtensionAPI lo aporta pi al cargar; aquí no hay dependencias.
export default function trinityVoice(pi: any): void {
	let spokeThisTurn = false;
	let lastError: Msg | undefined;
	const say = (text: string, why: string) => {
		if (!text || spokeThisTurn) return;
		spokeThisTurn = true;
		debug(`say (${why}): ${text.slice(0, 80)}`);
		run(["say"], spoken(text));
	};

	pi.on("before_agent_start", () => {
		spokeThisTurn = false;
		lastError = undefined;
		debug("before_agent_start → hush");
		run(["hush"]);
	});
	// Un error del proveedor puede no llegar en agent_end: lo recordamos aquí.
	pi.on("message_end", (event: { message?: Msg }) => {
		const m = event.message;
		if (m?.role === "assistant" && m.stopReason === "error") {
			lastError = m;
			debug(`message_end error: ${(m.errorMessage ?? "").slice(0, 80)}`);
		}
	});
	pi.on("agent_end", (event: { messages?: Msg[] }) => {
		debug(`agent_end msgs=${event.messages?.length ?? 0}`);
		const answer = answerOf(event.messages);
		if (answer) say(answer, "agent_end");
		else if (lastError) say(spokenError(lastError.errorMessage ?? ""), "error");
	});
	// Red de seguridad: si el turno se asentó con error y aún no hemos dicho nada.
	pi.on("agent_settled", () => {
		debug("agent_settled");
		if (lastError) say(spokenError(lastError.errorMessage ?? ""), "settled-error");
	});
}
