#!/usr/bin/env bash
# Riporta l'harness allo stato di un checkout pulito, cancellando ciò che le sessioni hanno
# prodotto. Chiamato da `make reset` e `make reset-all`; non va lanciato con l'API attiva.
#
#   --all       anche la configurazione fatta dal Control Center (provider, MCP, skill, subagenti)
#   --yes       non chiede conferma
#   --dry-run   elenca cosa cancellerebbe e si ferma
#
# Non tocca mai `.env`, il codice, `output/` né l'immagine Docker della sandbox.

set -eo pipefail

cd "$(dirname "$0")/.."

ALL=0
YES=0
DRY=0
for arg in "$@"; do
	case "$arg" in
		--all) ALL=1 ;;
		--yes) YES=1 ;;
		--dry-run) DRY=1 ;;
		*) echo "Opzione sconosciuta: $arg" >&2; exit 2 ;;
	esac
done

API_PORT="${HARNESS_API_PORT:-8000}"

# Dati che le sessioni generano da sole. I `-shm`/`-wal` sono parte del database SQLite:
# lasciarli senza il file principale corrompe il prossimo avvio.
SESSION_PATHS=(
	state/control.sqlite state/control.sqlite-shm state/control.sqlite-wal
	state/checkpoints.sqlite state/checkpoints.sqlite-shm state/checkpoints.sqlite-wal
	state/durable.sqlite state/durable.sqlite-shm state/durable.sqlite-wal
	state/audit.jsonl
	state/sessions
	state/evaluations
	state/improvements
	state/canary.json
	state/config_versions
	state/harness_overrides.toml
	state/_catalog
)

# Configurazione salvata dal Control Center: si azzera solo con --all.
CONFIG_PATHS=(
	state/provider_overrides.json
	state/mcp.json
	state/rubric.md
)

existing=()
for path in "${SESSION_PATHS[@]}"; do
	[ -e "$path" ] && existing+=("$path")
done
while IFS= read -r path; do
	existing+=("$path")
done < <(find workspace -mindepth 1 -maxdepth 1 ! -name .gitkeep 2>/dev/null)
if [ "$ALL" = 1 ]; then
	for path in "${CONFIG_PATHS[@]}"; do
		[ -e "$path" ] && existing+=("$path")
	done
	while IFS= read -r path; do
		existing+=("$path")
	done < <(find .agents/skills -mindepth 1 -maxdepth 1 2>/dev/null)
fi

memory_dirty=0
git diff --quiet -- memories/AGENTS.md 2>/dev/null || memory_dirty=1

subagents_dirty=0
if [ "$ALL" = 1 ] && [ -n "$(git status --porcelain -- subagents 2>/dev/null)" ]; then
	subagents_dirty=1
fi

containers=()
networks=()
if docker version >/dev/null 2>&1; then
	while IFS= read -r name; do
		[ -n "$name" ] && containers+=("$name")
	done < <(docker ps -a --format '{{.Names}}' --filter name=harness-sbx- 2>/dev/null)
	while IFS= read -r name; do
		[ -n "$name" ] && networks+=("$name")
	done < <(docker network ls --format '{{.Name}}' --filter name=harness-net- 2>/dev/null)
else
	echo "Docker non attivo: container e reti sandbox non verranno controllati."
fi

total=$(( ${#existing[@]} + ${#containers[@]} + ${#networks[@]} + memory_dirty + subagents_dirty ))
if [ "$total" = 0 ]; then
	echo "Niente da azzerare: l'harness è già allo stato iniziale."
	exit 0
fi

echo "Verrà cancellato:"
for path in "${existing[@]}"; do
	printf '  %-40s %s\n' "$path" "$(du -sh "$path" 2>/dev/null | cut -f1)"
done
for name in "${containers[@]}"; do echo "  container sandbox  $name"; done
for name in "${networks[@]}"; do echo "  rete sandbox       $name"; done
[ "$memory_dirty" = 1 ] && echo "  memories/AGENTS.md                       → versione in git"
[ "$subagents_dirty" = 1 ] && echo "  subagents/                               → versione in git"
echo
if [ "$ALL" = 1 ]; then
	echo "Restano: .env, codice, output/, immagine sandbox."
else
	echo "Restano: .env, provider e MCP impostati dal Control Center, skill, subagenti,"
	echo "output/, immagine sandbox. Per azzerare anche quelli: make reset-all"
fi

if [ "$DRY" = 1 ]; then
	exit 0
fi

# Con l'API accesa i database sono aperti: cancellarli lascerebbe il processo a scrivere su
# file che non esistono più, e al riavvio lo stato sarebbe a metà.
if lsof -nP -iTCP:"$API_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
	echo
	echo "L'API è attiva sulla porta $API_PORT. Fermala (Ctrl+C su make run / make api), poi riprova." >&2
	exit 1
fi

if [ "$YES" != 1 ]; then
	echo
	printf 'Scrivi "reset" per confermare: '
	read -r answer
	if [ "$answer" != "reset" ]; then
		echo "Annullato, nulla è stato cancellato."
		exit 1
	fi
fi

for name in "${containers[@]}"; do docker rm -f "$name" >/dev/null; done
for name in "${networks[@]}"; do docker network rm "$name" >/dev/null 2>&1 || true; done
for path in "${existing[@]}"; do rm -rf -- "$path"; done
[ "$memory_dirty" = 1 ] && git checkout -- memories/AGENTS.md
if [ "$subagents_dirty" = 1 ]; then
	git checkout -- subagents
	git clean -fdq -- subagents
fi

echo "Fatto: $total elementi azzerati. Al prossimo avvio l'harness ricrea ciò che gli serve."
