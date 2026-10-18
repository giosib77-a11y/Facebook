#!/usr/bin/env bash
# Stop / SubagentStop hook: Claude-ის ან executor-ის დასრულებისას უშვებს სწრაფ შემოწმებებს.
# თუ რომელიმე ჩავარდა, exit 2 შეცდომას Claude-ს უბრუნებს და აიძულებს გააგრძელოს მუშაობა.
#
# ბრძანებებს ავტომატურად პოულობს: package.json-ის scripts (lint, typecheck, test)
# ან Python-ის პროექტი (ruff, pytest; uv-ით, თუ uv.lock არსებობს).
# საკუთარი სიის მისათითებლად შეავსე CHECKS — მაშინ ავტომატური ძებნა გამოირთვება.
# ეს ფაილი მხოლოდ შენ (მომხმარებელი) შეცვალე; Claude-ს მისი რედაქტირება აკრძალული აქვს.
CHECKS=(
  # "pnpm lint"
  # "uv run pytest -q"
)

INPUT=$(cat)

# უსასრულო ციკლისგან დაცვა: თუ Claude უკვე ამ hook-ის გამო აგრძელებს, აღარ დაბლოკო.
if echo "$INPUT" | grep -q '"stop_hook_active"[[:space:]]*:[[:space:]]*true'; then
  exit 0
fi

# გზის შეცდომისას ჩუმად არ გავიდეთ: შეტყობინება ჩანს, მაგრამ მუშაობას არ ბლოკავს.
if ! cd "${CLAUDE_PROJECT_DIR:-.}" 2>/dev/null; then
  echo "verify.sh: პროექტის საქაღალდეში გადასვლა ვერ მოხერხდა ('${CLAUDE_PROJECT_DIR}'). შემოწმებები არ გაშვებულა." >&2
  exit 1
fi

# თუ git-ში ცვლილება არ არის (მაგ. მხოლოდ საუბარი იყო), შემოწმება არ გაეშვება.
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  [ -z "$(git status --porcelain)" ] && exit 0
fi

# ---- ავტომატური ძებნა, თუ CHECKS ცარიელია ----
if [ ${#CHECKS[@]} -eq 0 ]; then
  if [ -f package.json ] && command -v node >/dev/null 2>&1; then
    PM="npm"
    [ -f pnpm-lock.yaml ] && command -v pnpm >/dev/null 2>&1 && PM="pnpm"
    SCRIPTS=$(node -e "try{const s=require('./package.json').scripts||{};console.log(Object.keys(s).join(' '))}catch(e){}")
    for s in lint typecheck test; do
      [[ " $SCRIPTS " == *" $s "* ]] && CHECKS+=("$PM run $s")
    done
  fi
  if [ -f pyproject.toml ] || [ -f requirements.txt ]; then
    RUN=""
    [ -f uv.lock ] && command -v uv >/dev/null 2>&1 && RUN="uv run "
    if grep -qs "ruff" pyproject.toml requirements*.txt 2>/dev/null; then
      CHECKS+=("${RUN}ruff check .")
    fi
    if [ -d tests ] || ls test_*.py >/dev/null 2>&1; then
      CHECKS+=("${RUN}python -m pytest -q")
    fi
  fi
fi

[ ${#CHECKS[@]} -eq 0 ] && exit 0

# dependency-ები ჯერ დაყენებული არ არის → ცრუ ჩავარდნის ნაცვლად გაფრთხილება.
if [ -f package.json ] && [ ! -d node_modules ]; then
  echo "verify.sh: node_modules არ არის (გაუშვი install). Node-ის შემოწმებები გამოტოვებულია." >&2
  exit 1
fi

# test runner-ები (vitest, jest) ერთჯერადად ეშვება და არა watch რეჟიმში.
export CI=true

FAILED=0
for cmd in "${CHECKS[@]}"; do
  OUTPUT=$(bash -c "$cmd" 2>&1)
  if [ $? -ne 0 ]; then
    FAILED=1
    echo "Verification failed: $cmd" >&2
    echo "$OUTPUT" | tail -40 >&2
    echo "" >&2
  fi
done

if [ $FAILED -ne 0 ]; then
  echo "Fix the failures above before finishing. If a failure is unrelated to your change, explain it to the user instead." >&2
  exit 2
fi
exit 0
