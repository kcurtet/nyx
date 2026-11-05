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

/** Texto del último mensaje del asistente del turno. */
function answerOf(messages: { role?: string; content?: unknown }[] = []): string {
	for (let i = messages.length - 1; i >= 0; i--) {
		const m = messages[i]!;
		if (m.role !== "assistant") continue;
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
	pi.on("agent_end", (event: { messages?: { role?: string; content?: unknown }[] }) => {
		const text = spoken(answerOf(event.messages));
		if (text) run(["say"], text);
	});
}
