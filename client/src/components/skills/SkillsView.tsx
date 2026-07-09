import {
  AlertTriangle,
  Check,
  ChevronDown,
  ChevronRight,
  Download,
  FileText,
  History,
  Pencil,
  Plus,
  Sparkles,
  Trash2,
  Upload,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  createSkill,
  deleteSkill,
  deleteSkillFile,
  getSkill,
  getSkillFile,
  installSkill,
  listSkillFiles,
  listSkillInstalls,
  listSkills,
  putSkillFile,
  updateSkill,
  uploadSkillFile,
} from "../../api";
import { PanelEmpty } from "../shared/PanelEmpty";
import type { Skill, SkillFile, SkillInstall, SkillInstallSource } from "../../types";

const SOURCE_LABELS: Record<SkillInstallSource, string> = {
  archive_url: "URL archivio (.zip/.tar.gz)",
  git: "Repo git",
  registry: "Registry agentskills.io",
};

export function SkillsView() {
  const [skills, setSkills] = useState<Skill[]>([]);
  const [installs, setInstalls] = useState<SkillInstall[]>([]);
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [body, setBody] = useState("# Come procedere\n\n1. \n2. \n");
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);

  // Installazione da fonte esterna
  const [installOpen, setInstallOpen] = useState(false);
  const [source, setSource] = useState<SkillInstallSource>("archive_url");
  const [value, setValue] = useState("");
  const [gitRef, setGitRef] = useState("");
  const [subdir, setSubdir] = useState("");
  const [force, setForce] = useState(false);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setSkills(await listSkills());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Caricamento skill fallito");
    }
    // Storico separato: un backend senza la rotta non deve svuotare la lista skill.
    try {
      setInstalls(await listSkillInstalls());
    } catch {
      setInstalls([]);
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

  const install = async () => {
    setError("");
    setBusy(true);
    try {
      await installSkill({
        source,
        value: value.trim(),
        ref: source === "git" && gitRef.trim() ? gitRef.trim() : null,
        subdir: source === "git" && subdir.trim() ? subdir.trim() : null,
        force,
      });
      setValue("");
      setGitRef("");
      setSubdir("");
      setForce(false);
      setInstallOpen(false);
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Installazione fallita");
    } finally {
      setBusy(false);
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
              · cartella con SKILL.md + risorse, caricate su richiesta. L'agente può crearle e
              installarle; le modifiche valgono dal run successivo.
            </p>
          </div>
          <button
            type="button"
            onClick={() => setInstallOpen((v) => !v)}
            className="flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-sm font-semibold hover:bg-surface-raised"
          >
            <Download size={16} />
            Installa
          </button>
          <button
            type="button"
            onClick={() => setCreating((value) => !value)}
            className="flex items-center gap-1.5 rounded-lg bg-accent px-3 py-2 text-sm font-semibold text-on-accent hover:bg-accent-soft"
          >
            <Plus size={16} />
            Nuova
          </button>
        </div>

        {error ? <p className="px-6 pt-4 text-sm text-danger">{error}</p> : null}

        {installOpen ? (
          <div className="space-y-3 border-b border-border p-6">
            <div className="flex flex-wrap gap-2">
              {(Object.keys(SOURCE_LABELS) as SkillInstallSource[]).map((key) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => setSource(key)}
                  className={`rounded-lg border px-3 py-1.5 text-xs ${
                    source === key
                      ? "border-accent bg-accent/10 text-accent"
                      : "border-border text-muted hover:text-foreground"
                  }`}
                >
                  {SOURCE_LABELS[key]}
                </button>
              ))}
            </div>
            <input
              value={value}
              onChange={(event) => setValue(event.target.value)}
              placeholder={
                source === "registry"
                  ? "nome-skill nel registry"
                  : source === "git"
                    ? "https://host/utente/repo.git"
                    : "https://…/skill.zip"
              }
              className="w-full rounded-lg border border-border bg-surface px-3 py-2 font-mono text-sm outline-none focus:border-accent"
            />
            {source === "git" ? (
              <div className="flex gap-2">
                <input
                  value={gitRef}
                  onChange={(event) => setGitRef(event.target.value)}
                  placeholder="ref/branch (opz.)"
                  className="w-1/2 rounded-lg border border-border bg-surface px-3 py-2 font-mono text-sm outline-none focus:border-accent"
                />
                <input
                  value={subdir}
                  onChange={(event) => setSubdir(event.target.value)}
                  placeholder="sottocartella (opz.)"
                  className="w-1/2 rounded-lg border border-border bg-surface px-3 py-2 font-mono text-sm outline-none focus:border-accent"
                />
              </div>
            ) : null}
            <div className="flex items-center justify-between">
              <label className="flex items-center gap-2 text-xs text-muted">
                <input
                  type="checkbox"
                  checked={force}
                  onChange={(event) => setForce(event.target.checked)}
                />
                Sovrascrivi se esiste
              </label>
              <button
                type="button"
                onClick={install}
                disabled={!value.trim() || busy}
                className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-on-accent hover:bg-accent-soft disabled:opacity-50"
              >
                {busy ? "Installazione…" : "Installa skill"}
              </button>
            </div>
          </div>
        ) : null}

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
              className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-on-accent hover:bg-accent-soft disabled:opacity-50"
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
                          className="flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1 text-xs font-semibold text-on-accent hover:bg-accent-soft"
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
                        {skill.has_assets ? (
                          <span className="rounded border border-border px-1.5 text-xs text-muted">
                            assets
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
                      <button
                        type="button"
                        onClick={() => setExpanded((v) => (v === skill.name ? null : skill.name))}
                        className="mt-2 flex items-center gap-1 text-xs text-muted hover:text-foreground"
                      >
                        {expanded === skill.name ? (
                          <ChevronDown size={13} />
                        ) : (
                          <ChevronRight size={13} />
                        )}
                        File ({skill.resource_count})
                      </button>
                      {expanded === skill.name ? (
                        <SkillFilesPanel skillName={skill.name} onError={setError} />
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

      {installs.length ? (
        <div className="rounded-xl border border-border bg-surface">
          <div className="flex items-center gap-2 border-b border-border px-6 py-4">
            <History size={16} className="text-muted" />
            <h3 className="text-sm font-semibold">Storico installazioni</h3>
          </div>
          <div className="divide-y divide-border">
            {installs
              .slice()
              .reverse()
              .map((entry, index) => (
                <div key={index} className="flex items-center gap-3 px-6 py-2.5 text-xs">
                  <span
                    className={`rounded px-1.5 py-0.5 ${
                      entry.action === "install"
                        ? "bg-success/10 text-success"
                        : "bg-danger/10 text-danger"
                    }`}
                  >
                    {entry.action === "install" ? "install" : "revoca"}
                  </span>
                  <span className="font-mono font-medium">{entry.name}</span>
                  <span
                    className={`rounded px-1.5 py-0.5 ${
                      entry.by === "agent" ? "bg-accent/10 text-accent" : "bg-surface-raised text-muted"
                    }`}
                  >
                    {entry.by === "agent" ? "agente" : "operatore"}
                  </span>
                  <span className="truncate text-muted-2">{entry.source}</span>
                  <span className="ml-auto shrink-0 text-muted-2">
                    {new Date(entry.ts).toLocaleString()}
                  </span>
                </div>
              ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}

function SkillFilesPanel({
  skillName,
  onError,
}: {
  skillName: string;
  onError: (message: string) => void;
}) {
  const [files, setFiles] = useState<SkillFile[]>([]);
  const [openFile, setOpenFile] = useState<string | null>(null);
  const [fileDraft, setFileDraft] = useState("");
  const [fileBinary, setFileBinary] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const refreshFiles = useCallback(async () => {
    try {
      setFiles((await listSkillFiles(skillName)).filter((file) => !file.is_dir));
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "Lettura file fallita");
    }
  }, [skillName, onError]);

  useEffect(() => {
    void refreshFiles();
  }, [refreshFiles]);

  const openContent = async (path: string) => {
    try {
      const detail = await getSkillFile(skillName, path);
      setOpenFile(path);
      setFileBinary(detail.binary);
      setFileDraft(detail.content);
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "Apertura file fallita");
    }
  };

  const saveFile = async () => {
    if (!openFile) return;
    try {
      await putSkillFile(skillName, openFile, fileDraft);
      setOpenFile(null);
      await refreshFiles();
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "Salvataggio file fallito");
    }
  };

  const removeFile = async (path: string) => {
    if (!window.confirm(`Eliminare "${path}"?`)) return;
    try {
      await deleteSkillFile(skillName, path);
      if (openFile === path) setOpenFile(null);
      await refreshFiles();
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "Eliminazione file fallita");
    }
  };

  const upload = async (file: File) => {
    try {
      await uploadSkillFile(skillName, file);
      await refreshFiles();
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "Upload fallito");
    }
  };

  return (
    <div className="mt-2 rounded-lg border border-border bg-background p-3">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-xs text-muted-2">
          Risorse (SKILL.md dalla matita; qui scripts/ references/ assets/)
        </span>
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          className="flex items-center gap-1 rounded border border-border px-2 py-1 text-xs text-muted hover:text-foreground"
        >
          <Upload size={12} />
          Carica
        </button>
        <input
          ref={inputRef}
          type="file"
          className="hidden"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) void upload(file);
            event.target.value = "";
          }}
        />
      </div>
      {files.length ? (
        <ul className="space-y-1">
          {files.map((file) => (
            <li key={file.path} className="flex items-center gap-2 text-xs">
              <FileText size={12} className="shrink-0 text-muted-2" />
              <button
                type="button"
                onClick={() => openContent(file.path)}
                className="truncate font-mono hover:text-accent"
              >
                {file.path}
              </button>
              <span className="shrink-0 text-muted-2">{file.size} B</span>
              <button
                type="button"
                onClick={() => removeFile(file.path)}
                aria-label="Elimina file"
                className="ml-auto shrink-0 rounded p-1 text-muted-2 hover:bg-danger/10 hover:text-danger"
              >
                <Trash2 size={12} />
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-xs text-muted-2">Nessun file di risorsa.</p>
      )}
      {openFile ? (
        <div className="mt-3 space-y-2">
          <div className="flex items-center justify-between">
            <span className="font-mono text-xs">{openFile}</span>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setOpenFile(null)}
                className="rounded border border-border px-2 py-0.5 text-xs text-muted hover:text-foreground"
              >
                Chiudi
              </button>
              {!fileBinary ? (
                <button
                  type="button"
                  onClick={saveFile}
                  className="rounded bg-accent px-2 py-0.5 text-xs font-semibold text-on-accent hover:bg-accent-soft"
                >
                  Salva
                </button>
              ) : null}
            </div>
          </div>
          {fileBinary ? (
            <p className="text-xs text-muted-2">File binario: anteprima/modifica non disponibili.</p>
          ) : (
            <textarea
              value={fileDraft}
              onChange={(event) => setFileDraft(event.target.value)}
              rows={10}
              className="w-full rounded-lg border border-border bg-surface px-3 py-2 font-mono text-xs outline-none focus:border-accent"
            />
          )}
        </div>
      ) : null}
    </div>
  );
}
