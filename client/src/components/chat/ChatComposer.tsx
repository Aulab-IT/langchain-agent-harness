import { ArrowUp, Cpu, Paperclip, ShieldCheck, Sparkles, Square, X, Zap } from "lucide-react";
import { useMemo, useRef, useState, type ChangeEvent, type FormEvent } from "react";
import { ACCEPTED_FILES } from "../../lib/constants";
import {
  SESSION_OVERRIDE_LABELS,
  modelMarker,
  withModelMarker,
  type MessageModel,
} from "../../lib/modelOverride";
import {
  activeSkillQuery,
  buildSkillConstraint,
  replaceSkillQuery,
  withSkillConstraint,
} from "../../lib/skillConstraint";
import type { ModelOverride, RuntimeSkill, SessionFile } from "../../types";
import { FileIcon } from "../shared/FileIcon";
import { SkillMenu } from "./SkillMenu";

const MESSAGE_MODEL_CYCLE: MessageModel[] = ["auto", "strong", "default"];
const MESSAGE_MODEL_LABELS: Record<MessageModel, string> = {
  auto: "Modello: automatico",
  strong: "Modello: forte",
  default: "Modello: base",
};

export function ChatComposer({
  disabled,
  files,
  skills,
  autoApprove,
  sessionModel,
  onSend,
  onUpload,
  onDeleteFile,
  onStop,
  onToggleAutoApprove,
  onSessionModel,
}: {
  disabled: boolean;
  files: SessionFile[];
  skills: RuntimeSkill[];
  autoApprove: boolean;
  sessionModel: ModelOverride;
  onSend: (content: string) => void;
  onUpload: (files: FileList | null) => void;
  onDeleteFile: (name: string) => void;
  onStop: () => void;
  onToggleAutoApprove: (enabled: boolean) => void;
  onSessionModel: (override: ModelOverride) => void;
}) {
  const [messageModel, setMessageModel] = useState<MessageModel>("auto");
  const [value, setValue] = useState("");
  const [query, setQuery] = useState<string | null>(null);
  const [highlighted, setHighlighted] = useState(0);
  const [selectedSkill, setSelectedSkill] = useState<string | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const matches = useMemo(() => {
    if (query === null) return [];
    const needle = query.toLowerCase();
    return skills.filter((skill) => skill.name.toLowerCase().includes(needle)).slice(0, 8);
  }, [query, skills]);
  const menuOpen = query !== null && matches.length > 0;

  const closeMenu = () => {
    setQuery(null);
    setHighlighted(0);
  };

  const chooseSkill = (skill: RuntimeSkill) => {
    const input = inputRef.current;
    const caret = input?.selectionStart ?? value.length;
    setValue(replaceSkillQuery(value, caret));
    setSelectedSkill(skill.name);
    closeMenu();
    input?.focus();
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const clean = value.trim();
    if (!clean || disabled) return;
    // Il marcatore del modello resta accanto al testo dell'utente; il vincolo skill va in fondo.
    onSend(withSkillConstraint(withModelMarker(clean, messageModel), selectedSkill));
    setValue("");
    setSelectedSkill(null);
    setMessageModel("auto");
    closeMenu();
    if (inputRef.current) inputRef.current.style.height = "auto";
  };

  const resize = (event: ChangeEvent<HTMLTextAreaElement>) => {
    const next = event.target.value;
    setValue(next);
    setQuery(activeSkillQuery(next, event.target.selectionStart));
    setHighlighted(0);
    event.target.style.height = "auto";
    event.target.style.height = `${Math.min(event.target.scrollHeight, 160)}px`;
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (menuOpen) {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        setHighlighted((current) => (current + 1) % matches.length);
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        setHighlighted((current) => (current - 1 + matches.length) % matches.length);
        return;
      }
      if (event.key === "Enter" || event.key === "Tab") {
        event.preventDefault();
        chooseSkill(matches[highlighted]);
        return;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        closeMenu();
        return;
      }
    }
    if (event.key === "Enter" && !event.shiftKey) submit(event);
  };

  return (
    <form
      className="relative z-10 shrink-0 border-t border-border bg-surface p-3"
      onSubmit={submit}
    >
      {files.length ? (
        <div className="mb-3 flex flex-wrap gap-2" aria-label="Allegati conversazione">
          {files.map((file) => (
            <span
              key={file.name}
              className="inline-flex max-w-[220px] items-center gap-2 rounded-lg border border-border bg-surface-raised px-3 py-2 text-sm"
              title={file.name}
            >
              <FileIcon type={file.type} />
              <span className="truncate">{file.name}</span>
              <button
                type="button"
                className="text-muted hover:text-foreground"
                aria-label={`Rimuovi ${file.name}`}
                onClick={() => onDeleteFile(file.name)}
              >
                <X size={14} />
              </button>
            </span>
          ))}
        </div>
      ) : null}
      {selectedSkill ? (
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <span
            className="inline-flex items-center gap-1.5 rounded-full border border-accent/30 bg-accent/10 px-3 py-1.5 text-sm text-accent"
            title={buildSkillConstraint(selectedSkill)}
          >
            <Sparkles size={13} />
            {selectedSkill}
            <button
              type="button"
              className="ml-0.5 hover:text-foreground"
              aria-label={`Rimuovi il vincolo sulla skill ${selectedSkill}`}
              onClick={() => setSelectedSkill(null)}
            >
              <X size={13} />
            </button>
          </span>
          <span className="text-xs text-muted">
            Il messaggio chiederà all'agente di leggere e seguire questa skill. È un vincolo
            forte, non una chiamata di funzione: l'agente resta libero di non applicarla.
          </span>
        </div>
      ) : null}
      <div className="relative rounded-xl border border-border bg-background shadow-sm transition-[border-color,box-shadow] focus-within:border-muted focus-within:shadow-[0_0_0_1px_rgba(250,204,21,0.14)]">
        {menuOpen ? (
          <SkillMenu skills={matches} highlighted={highlighted} onSelect={chooseSkill} />
        ) : null}
        <textarea
          ref={inputRef}
          className="block w-full resize-none bg-transparent px-4 pt-4 text-base leading-relaxed outline-none focus:outline-none focus-visible:outline-none placeholder:text-muted"
          value={value}
          onChange={resize}
          onKeyDown={onKeyDown}
          onBlur={closeMenu}
          placeholder="Dai un obiettivo all'agente…  /  per una skill"
          aria-label="Messaggio"
          aria-autocomplete="list"
          aria-expanded={menuOpen}
          maxLength={20_000}
          rows={1}
        />
        <div className="flex items-center justify-between gap-3 px-3 pb-3">
          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-sm text-muted hover:bg-surface-raised hover:text-foreground"
              onClick={() => fileRef.current?.click()}
            >
              <Paperclip size={16} />
              Allega
            </button>
            <input
              ref={fileRef}
              hidden
              multiple
              type="file"
              accept={ACCEPTED_FILES}
              onChange={(event) => onUpload(event.target.files)}
            />
            <button
              type="button"
              className={`hidden items-center gap-1.5 rounded-lg px-1.5 py-1 text-xs transition-colors sm:inline-flex ${
                autoApprove ? "text-warning hover:bg-warning/10" : "text-muted hover:bg-surface-raised hover:text-foreground"
              }`}
              onClick={() => onToggleAutoApprove(!autoApprove)}
              title={
                autoApprove
                  ? "L'agente esegue comandi sandbox senza chiedere conferma per questa sessione. Clicca per richiedere di nuovo l'approvazione."
                  : "L'agente chiede conferma prima di eseguire comandi nella sandbox Docker isolata. Clicca per farlo lavorare in autonomia."
              }
            >
              {autoApprove ? <Zap size={14} /> : <ShieldCheck size={14} />}
              {autoApprove ? "Sandbox autonoma" : "Sandbox con approvazione"}
            </button>
            <button
              type="button"
              className={`hidden items-center gap-1.5 rounded-lg px-1.5 py-1 text-xs transition-colors sm:inline-flex ${
                messageModel === "auto"
                  ? "text-muted hover:bg-surface-raised hover:text-foreground"
                  : "text-accent hover:bg-accent/10"
              }`}
              onClick={() =>
                setMessageModel(
                  (current) =>
                    MESSAGE_MODEL_CYCLE[
                      (MESSAGE_MODEL_CYCLE.indexOf(current) + 1) % MESSAGE_MODEL_CYCLE.length
                    ],
                )
              }
              title={
                messageModel === "auto"
                  ? "Il router sceglie il modello dal contenuto della richiesta. Clicca per forzarlo su questo messaggio."
                  : `Aggiunge ${modelMarker(messageModel)} in fondo al messaggio, in chiaro. Vale solo per questo invio.`
              }
            >
              <Cpu size={14} />
              {MESSAGE_MODEL_LABELS[messageModel]}
            </button>
          </div>
          <div className="flex items-center gap-3">
            <label className="hidden text-xs text-muted lg:inline">
              <span className="sr-only">Modello per questa sessione</span>
              <select
                className="rounded-lg border border-border bg-background px-2 py-1 text-xs text-muted hover:text-foreground"
                value={sessionModel}
                onChange={(event) => onSessionModel(event.target.value as ModelOverride)}
                title="Vale per tutti i messaggi della sessione. Un marcatore sul singolo messaggio lo scavalca."
              >
                {(Object.keys(SESSION_OVERRIDE_LABELS) as ModelOverride[]).map((key) => (
                  <option key={key} value={key}>
                    {SESSION_OVERRIDE_LABELS[key]}
                  </option>
                ))}
              </select>
            </label>
            <span className="hidden text-xs text-muted md:inline">Invio ↵ · A capo ⇧↵</span>
            {disabled ? (
              <button
                type="button"
                onClick={onStop}
                className="flex h-9 w-9 items-center justify-center rounded-lg bg-danger/10 text-danger hover:bg-danger/20"
                aria-label="Ferma esecuzione"
                title="Ferma esecuzione"
              >
                <Square size={16} fill="currentColor" />
              </button>
            ) : (
              <button
                type="submit"
                className="flex h-9 w-9 items-center justify-center rounded-lg bg-accent text-on-accent hover:bg-accent-soft disabled:opacity-40"
                disabled={!value.trim()}
                aria-label="Invia messaggio"
              >
                <ArrowUp size={18} />
              </button>
            )}
          </div>
        </div>
      </div>
    </form>
  );
}
