import { AlertTriangle, Check, Pencil, Plus, Sparkles, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { createSkill, deleteSkill, getSkill, listSkills, updateSkill } from "../../api";
import { PanelEmpty } from "../shared/PanelEmpty";
import type { Skill } from "../../types";

export function SkillsView() {
  const [skills, setSkills] = useState<Skill[]>([]);
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [body, setBody] = useState("# Come procedere\n\n1. \n2. \n");
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");

  const refresh = useCallback(async () => {
    try {
      setSkills(await listSkills());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Caricamento skill fallito");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const create = async () => {
    setError("");
    try {
      await createSkill({ name: name.trim(), description: description.trim(), body });
      setName("");
      setDescription("");
      setBody("# Come procedere\n\n1. \n2. \n");
      setCreating(false);
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Creazione fallita");
    }
  };

  const openEditor = async (skillName: string) => {
    setError("");
    try {
      const detail = await getSkill(skillName);
      setEditing(skillName);
      setDraft(detail.content);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Apertura skill fallita");
    }
  };

  const save = async () => {
    if (!editing) return;
    setError("");
    try {
      await updateSkill(editing, draft);
      setEditing(null);
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Salvataggio fallito");
    }
  };

  const remove = async (skillName: string) => {
    if (!window.confirm(`Eliminare la skill "${skillName}"?`)) return;
    try {
      await deleteSkill(skillName);
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Eliminazione fallita");
    }
  };

  return (
    <section className="mx-auto w-full max-w-4xl space-y-4">
      <div className="rounded-xl border border-border bg-surface">
        <div className="flex items-center gap-3 border-b border-border px-6 py-5">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg border border-accent/20 bg-accent/10 text-accent">
            <Sparkles size={18} />
          </div>
          <div className="flex-1">
            <h2 className="text-lg font-semibold">Skills</h2>
            <p className="text-sm text-muted">
              Standard{" "}
              <a
                href="https://agentskills.io"
                target="_blank"
                rel="noopener noreferrer"
                className="text-accent hover:underline"
              >
                Agent Skills
              </a>{" "}
              · caricate su richiesta (progressive disclosure). Le modifiche valgono dal run
              successivo.
            </p>
          </div>
          <button
            type="button"
            onClick={() => setCreating((value) => !value)}
            className="flex items-center gap-1.5 rounded-lg bg-accent px-3 py-2 text-sm font-medium text-white hover:bg-accent-soft"
          >
            <Plus size={16} />
            Nuova
          </button>
        </div>

        {error ? <p className="px-6 pt-4 text-sm text-danger">{error}</p> : null}

        {creating ? (
          <div className="space-y-3 border-b border-border p-6">
            <div>
              <input
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="nome-skill (minuscole, cifre, trattini)"
                className="w-full rounded-lg border border-border bg-surface px-3 py-2 font-mono text-sm outline-none focus:border-accent"
              />
              <p className="mt-1 text-xs text-muted-2">
                Deve coincidere con la cartella: minuscole a-z, cifre e trattini singoli (max 64).
              </p>
            </div>
            <textarea
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder="Descrizione: cosa fa e quando usarla (max 1024 caratteri)"
              rows={2}
              className="w-full resize-none rounded-lg border border-border bg-surface px-3 py-2 text-sm outline-none focus:border-accent"
            />
            <textarea
              value={body}
              onChange={(event) => setBody(event.target.value)}
              placeholder="Istruzioni in Markdown"
              rows={5}
              className="w-full rounded-lg border border-border bg-surface px-3 py-2 font-mono text-sm outline-none focus:border-accent"
            />
            <button
              type="button"
              onClick={create}
              disabled={!name.trim() || !description.trim()}
              className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-soft disabled:opacity-50"
            >
              Crea skill
            </button>
          </div>
        ) : null}

        <div className="divide-y divide-border">
          {skills.length ? (
            skills.map((skill) => (
              <div key={skill.name} className="px-6 py-4">
                {editing === skill.name ? (
                  <div className="space-y-2">
                    <div className="flex items-center justify-between">
                      <span className="font-mono text-sm font-medium">{skill.name}/SKILL.md</span>
                      <div className="flex gap-2">
                        <button
                          type="button"
                          onClick={() => setEditing(null)}
                          className="rounded-lg border border-border px-3 py-1 text-xs text-muted hover:text-foreground"
                        >
                          Annulla
                        </button>
                        <button
                          type="button"
                          onClick={save}
                          className="flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1 text-xs font-medium text-white hover:bg-accent-soft"
                        >
                          <Check size={13} />
                          Salva
                        </button>
                      </div>
                    </div>
                    <textarea
                      value={draft}
                      onChange={(event) => setDraft(event.target.value)}
                      rows={14}
                      className="w-full rounded-lg border border-border bg-background px-3 py-2 font-mono text-xs outline-none focus:border-accent"
                    />
                  </div>
                ) : (
                  <div className="flex items-start gap-3">
                    <span
                      className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border ${
                        skill.valid
                          ? "border-success/20 bg-success/10 text-success"
                          : "border-danger/20 bg-danger/10 text-danger"
                      }`}
                    >
                      {skill.valid ? <Sparkles size={15} /> : <AlertTriangle size={15} />}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-mono text-sm font-medium">{skill.name}</span>
                        {skill.valid ? (
                          <span className="rounded-full bg-success/10 px-2 py-0.5 text-xs text-success">
                            conforme
                          </span>
                        ) : (
                          <span className="rounded-full bg-danger/10 px-2 py-0.5 text-xs text-danger">
                            {skill.errors.length} errori
                          </span>
                        )}
                        {skill.license ? (
                          <span className="text-xs text-muted-2">{skill.license}</span>
                        ) : null}
                        {skill.has_scripts ? (
                          <span className="rounded border border-border px-1.5 text-xs text-muted">
                            scripts
                          </span>
                        ) : null}
                        {skill.has_references ? (
                          <span className="rounded border border-border px-1.5 text-xs text-muted">
                            references
                          </span>
                        ) : null}
                      </div>
                      <p className="mt-1 text-sm text-muted">{skill.description}</p>
                      {!skill.valid ? (
                        <ul className="mt-1 list-disc pl-5 text-xs text-danger">
                          {skill.errors.map((issue, index) => (
                            <li key={index}>{issue}</li>
                          ))}
                        </ul>
                      ) : null}
                    </div>
                    <div className="flex shrink-0 gap-1">
                      <button
                        type="button"
                        onClick={() => openEditor(skill.name)}
                        aria-label="Modifica"
                        className="rounded-md p-1.5 text-muted hover:bg-surface-raised hover:text-foreground"
                      >
                        <Pencil size={15} />
                      </button>
                      <button
                        type="button"
                        onClick={() => remove(skill.name)}
                        aria-label="Elimina"
                        className="rounded-md p-1.5 text-muted hover:bg-danger/10 hover:text-danger"
                      >
                        <Trash2 size={15} />
                      </button>
                    </div>
                  </div>
                )}
              </div>
            ))
          ) : (
            <PanelEmpty>Nessuna skill. Creane una per dare procedure riutilizzabili all'agente.</PanelEmpty>
          )}
        </div>
      </div>
    </section>
  );
}
