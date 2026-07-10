import { Sparkles } from "lucide-react";
import { useEffect, useRef } from "react";
import type { RuntimeSkill } from "../../types";

export function SkillMenu({
  skills,
  highlighted,
  onSelect,
}: {
  skills: RuntimeSkill[];
  highlighted: number;
  onSelect: (skill: RuntimeSkill) => void;
}) {
  const activeRef = useRef<HTMLLIElement>(null);

  useEffect(() => {
    activeRef.current?.scrollIntoView({ block: "nearest" });
  }, [highlighted]);

  if (!skills.length) return null;

  return (
    <div className="absolute bottom-full left-0 z-20 mb-2 w-full max-w-md overflow-hidden rounded-xl border border-border bg-surface shadow-2xl">
      <ul className="max-h-64 overflow-y-auto" role="listbox" aria-label="Skill disponibili">
        {skills.map((skill, index) => (
          <li
            key={skill.name}
            ref={index === highlighted ? activeRef : null}
            role="option"
            aria-selected={index === highlighted}
          >
            <button
              type="button"
              className={`flex w-full items-start gap-2.5 px-4 py-2.5 text-left ${
                index === highlighted ? "bg-accent/10" : "hover:bg-surface-raised"
              }`}
              // onMouseDown, non onClick: il blur del textarea chiuderebbe il menu prima
              // che il click arrivi.
              onMouseDown={(event) => {
                event.preventDefault();
                onSelect(skill);
              }}
            >
              <Sparkles
                size={13}
                className={`mt-1 shrink-0 ${index === highlighted ? "text-accent" : "text-muted"}`}
              />
              <span className="min-w-0">
                <span className="block font-mono text-sm text-foreground">{skill.name}</span>
                <span className="line-clamp-2 block text-xs text-muted">{skill.description}</span>
              </span>
            </button>
          </li>
        ))}
      </ul>
      <p className="border-t border-border px-4 py-2 text-xs text-muted">
        ↑↓ per scorrere · ↵ per scegliere · esc per annullare
      </p>
    </div>
  );
}
