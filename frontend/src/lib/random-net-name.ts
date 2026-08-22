/**
 * Generates a default name for a new net, so a fresh canvas reads as
 * something more specific than "Untitled" before the user renames it.
 * Two adjectives plus a noun in snake_case, themed around flow/process
 * words to fit a Petri net simulator (e.g. "swift_quiet_relay").
 */

const ADJECTIVES = [
  "swift", "quiet", "bold", "calm", "brisk", "keen", "vivid", "steady",
  "bright", "subtle", "rapid", "solid", "gentle", "sharp", "clever",
  "silent", "eager", "prime", "fresh", "agile", "lucid", "nimble",
  "tidy", "broad", "deep", "wild", "lively", "crisp", "stout", "mellow",
];

const NOUNS = [
  "flow", "token", "gate", "loop", "signal", "engine", "circuit", "pulse",
  "relay", "queue", "buffer", "stream", "cycle", "network", "graph",
  "node", "vertex", "path", "trace", "beacon", "channel", "current",
  "junction", "pipeline", "cascade", "sequence", "trigger", "marker",
  "ledger", "compass",
];

function pick(words: string[]): string {
  return words[Math.floor(Math.random() * words.length)];
}

export function randomNetName(): string {
  return [pick(ADJECTIVES), pick(ADJECTIVES), pick(NOUNS)].join("_");
}
