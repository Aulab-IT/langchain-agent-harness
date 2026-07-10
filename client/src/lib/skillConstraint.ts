/**
 * L'agente non ha un modo di *invocare* una skill: le skill sono documenti che sceglie di
 * leggere quando la descrizione gli sembra pertinente. Selezionare una skill con `/` non può
 * quindi essere una chiamata di funzione, e fingere che lo sia produrrebbe un'interfaccia che
 * promette determinismo dove non ce n'è.
 *
 * Quello che possiamo fare è trasformare la selezione in un vincolo esplicito, scritto nel
 * messaggio in chiaro: l'utente vede esattamente cosa è stato chiesto all'agente, e nulla
 * viene aggiunto al prompt di nascosto.
 */

export const SKILL_TOKEN = /(^|\s)\/([a-z0-9-]*)$/;

export function buildSkillConstraint(skillName: string): string {
  return (
    `[Vincolo] Usa la skill "${skillName}": leggi /skills/${skillName}/SKILL.md ` +
    "e segui la procedura descritta lì."
  );
}

export function withSkillConstraint(message: string, skillName: string | null): string {
  const clean = message.trim();
  if (!skillName) return clean;
  return `${clean}\n\n${buildSkillConstraint(skillName)}`;
}

/** Il frammento `/xyz` che l'utente sta digitando, oppure `null` se non ne sta digitando uno. */
export function activeSkillQuery(text: string, caret: number): string | null {
  const match = SKILL_TOKEN.exec(text.slice(0, caret));
  return match ? match[2] : null;
}

export function replaceSkillQuery(text: string, caret: number): string {
  const before = text.slice(0, caret).replace(SKILL_TOKEN, "$1");
  return before + text.slice(caret);
}
