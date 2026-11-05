/**
 * jerga · voz de la Capitana (extensión de pi).
 *
 * - Al empezar un turno (llega una orden nueva): `jerga hush` — calla lo que se estuviera leyendo.
 * - Al terminar el turno: lee la respuesta final con `jerga say` (phonon + lexicón + normalizador).
 *   Respuestas largas: solo el principio y "el resto está en el panel".
 *
 * Se carga solo en la sesión de la Capitana (`jerga capitana` la arranca con -e).
 */
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import os from "node:os";
import path from "node:path";

const MAX_SPOKEN = 420;

function jergaBin(): string {
	const env = process.env.JERGA_BIN;
	if (env) return env;
	const local = path.join(os.homedir(), ".local", "bin", "jerga");
	return existsSync(local) ? local : "jerga";
}

function run(args: string[], stdin?: string): void {
	try {
		const child = spawn(jergaBin(), args, { stdio: [stdin === undefined ? "ignore" : "pipe", "ignore", "ignore"] });
		child.on("error", () => {});
		if (stdin !== undefined) child.stdin?.end(stdin);
	} catch {
		// la voz nunca rompe el turno
	}
}

type Msg = { role?: string; content?: unknown; stopReason?: string; errorMessage?: string };

/** Error del modelo en palabras que se entiendan al oído (el original puede venir hasta en chino). */
export function spokenError(err: string): string {
	const e = err.toLowerCase();
	if (/\b429\b|rate.?limit|quota|limit|上限|限额/.test(e)) return "No puedo responder: has llegado al límite de uso del modelo.";
	if (/\b40[13]\b|auth|api key|unauthori[sz]ed|forbidden/.test(e)) return "No puedo responder: hay un problema de autenticación con el modelo.";
	if (/timeout|timed out|etimedout|econn|network|fetch failed|enotfound|\b50[234]\b|overloaded/.test(e))
		return "No puedo responder: no hay conexión con el modelo o está saturado. Prueba en un momento.";
	return "El modelo ha devuelto un error. Tienes el detalle en el panel.";
}

/** Texto del último mensaje del asistente del turno (o el aviso de error si el turno falló). */
function answerOf(messages: Msg[] = []): string {
	for (let i = messages.length - 1; i >= 0; i--) {
		const m = messages[i]!;
		if (m.role !== "assistant") continue;
		if (m.stopReason === "error") return spokenError(m.errorMessage ?? "");
		if (typeof m.content === "string") return m.content;
		if (Array.isArray(m.content)) {
			return m.content
				.filter((c): c is { type: string; text: string } => typeof c === "object" && c !== null && (c as { type?: string }).type === "text")
				.map((c) => c.text)
				.join("");
		}
		return "";
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

// biome-ignore lint: el tipo de ExtensionAPI viene de pi en tiempo de carga
export default function capitanaVoice(pi: any): void {
	pi.on("before_agent_start", () => run(["hush"]));
	pi.on("agent_end", (event: { messages?: Msg[] }) => {
		const text = spoken(answerOf(event.messages));
		if (text) run(["say"], text);
	});
}
