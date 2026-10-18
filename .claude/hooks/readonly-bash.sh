#!/usr/bin/env bash
# PreToolUse hook (code-reviewer, security-auditor): Bash-ზე მხოლოდ წასაკითხ ბრძანებებს უშვებს.
# გამოყენება: readonly-bash.sh reviewer | auditor
#   auditor  — მხოლოდ კითხვა: git (წასაკითხი ქვებრძანებები), grep/cat/ls/find..., npm/pnpm audit, pip-audit (fix-ის გარეშე)
#   reviewer — იგივე + პროექტის არსებული ტესტები და შემოწმებები (test, lint, typecheck)
# ყველაფერი დანარჩენი იბლოკება (exit 2) და მიზეზი აგენტს უბრუნდება.
# ეს ფაილი მხოლოდ შენ (მომხმარებელი) შეცვალე; Claude-ს მისი რედაქტირება აკრძალული აქვს.

MODE="${1:-auditor}"
INPUT=$(cat)

block() {
  echo "Blocked by readonly-bash.sh ($MODE): $1" >&2
  echo "ამ აგენტს Bash-ზე მხოლოდ წასაკითხი ბრძანებები აქვს ნებადართული (git diff/log/show/status/blame, grep, rg, cat, head, tail, ls, find$( [ "$MODE" = reviewer ] && echo ', npm/pnpm test|lint|typecheck, pytest, node --test, vitest run, tsc --noEmit' ), npm/pnpm audit, pip-audit). ფაილების შეცვლა, ინსტალაცია, commit და სხვა სკრიპტები აკრძალულია." >&2
  exit 2
}

# ---- tool_input.command-ის ამოღება (jq → node → python3 → python); ვერ ამოიღო → დაბლოკე ----
COMMAND=""; PARSED=0
if command -v jq >/dev/null 2>&1; then
  COMMAND=$(printf '%s' "$INPUT" | jq -r '.tool_input.command // ""' 2>/dev/null) && PARSED=1
fi
if [ $PARSED -eq 0 ] && command -v node >/dev/null 2>&1; then
  COMMAND=$(printf '%s' "$INPUT" | node -e 'let d="";process.stdin.on("data",c=>d+=c).on("end",()=>{try{process.stdout.write(String((JSON.parse(d).tool_input||{}).command||""))}catch(e){process.exit(3)}})' 2>/dev/null) && PARSED=1
fi
for PY in python3 python; do
  [ $PARSED -eq 1 ] && break
  if command -v "$PY" >/dev/null 2>&1; then
    COMMAND=$(printf '%s' "$INPUT" | "$PY" -c 'import sys,json;sys.stdout.write(str((json.load(sys.stdin).get("tool_input") or {}).get("command","")))' 2>/dev/null) && PARSED=1
  fi
done
[ $PARSED -eq 1 ] || block "hook-ის input-ის წაკითხვა ვერ მოხერხდა (jq, node ან python საჭიროა)"
[ -z "$COMMAND" ] && exit 0

# ---- აშკარად სახიფათო კონსტრუქციები ----
case "$COMMAND" in
  *$'\n'*) block "მრავალხაზიანი ბრძანება" ;;
  *'`'*|*'$('*|*'<('*|*'>('*) block "command substitution" ;;
esac

# ---- უსაფრთხო გადამისამართებების მოცილება, მერე ნებისმიერი '>' იბლოკება ----
CLEAN=$(printf '%s' "$COMMAND" | sed -E 's#[0-9]*>&[0-9]+##g; s#[0-9]*> */dev/null##g')

# ---- ბრძანების დაყოფა სეგმენტებად (|, ||, &&, ;, &) ბრჭყალების გათვალისწინებით ----
SEGMENTS=(); CUR=""; SQ=0; DQ=0
for (( i=0; i<${#CLEAN}; i++ )); do
  c="${CLEAN:$i:1}"
  if [ $SQ -eq 1 ]; then [ "$c" = "'" ] && SQ=0; CUR+="$c"; continue; fi
  if [ $DQ -eq 1 ]; then [ "$c" = '"' ] && DQ=0; CUR+="$c"; continue; fi
  case "$c" in
    "'") SQ=1; CUR+="$c" ;;
    '"') DQ=1; CUR+="$c" ;;
    '>') block "ფაილში ჩაწერა (redirection)" ;;
    '|'|';'|'&') SEGMENTS+=("$CUR"); CUR="" ;;
    *) CUR+="$c" ;;
  esac
done
SEGMENTS+=("$CUR")

has_arg() { local a; for a in "${ARGS[@]}"; do case "$a" in $1) return 0 ;; esac; done; return 1; }

check_git() {
  local i=1 sub
  while [ $i -lt ${#ARGS[@]} ]; do
    case "${ARGS[$i]}" in
      --no-pager) i=$((i+1)) ;;
      -C) i=$((i+2)) ;;
      -c|--config-env*|--exec-path*) block "git-ის კონფიგურაციის შეცვლა ბრძანებიდან" ;;
      *) break ;;
    esac
  done
  sub="${ARGS[$i]}"
  has_arg '--output*' && block "git --output (ფაილში ჩაწერა)"
  has_arg '--ext-diff' && block "git --ext-diff (გარე პროგრამა)"
  case "$sub" in
    status|diff|log|show|blame|rev-parse|ls-files|ls-tree|shortlog|describe|cat-file|rev-list|show-ref|reflog) ;;
    grep) has_arg '-O*' && block "git grep -O"; has_arg '--open-files-in-pager*' && block "git grep --open-files-in-pager" ;;
    branch)
      local j
      for (( j=i+1; j<${#ARGS[@]}; j++ )); do
        case "${ARGS[$j]}" in -a|-r|-v|-vv|--list|--show-current|--all|--remotes|--contains|--merged|--no-merged) ;; *) block "git branch მხოლოდ სიის სანახავად" ;; esac
      done ;;
    *) block "git $sub" ;;
  esac
}

check_tests() {   # მხოლოდ reviewer რეჟიმში
  [ "$MODE" = reviewer ] || return 1
  local w0="${ARGS[0]}" w1="${ARGS[1]}" w2="${ARGS[2]}"
  case "$w0 $w1" in
    "npm test"|"pnpm test") return 0 ;;
    "npm run"|"pnpm run") case "$w2" in test|lint|typecheck) return 0 ;; esac; return 1 ;;
    "node --test") return 0 ;;
    "pytest "*|"pytest") return 0 ;;
  esac
  case "$w0 $w1 $w2" in
    "python -m pytest"*|"python3 -m pytest"*|"uv run pytest"*) return 0 ;;
    "npx vitest run"*|"pnpm exec vitest"*) [ "$w0 $w1" = "pnpm exec" ] && [ "${ARGS[3]}" != run ] && return 1; return 0 ;;
    "npx tsc "*|"npx tsc") has_arg '--noEmit' && return 0; return 1 ;;
    "npx eslint"*) has_arg '--fix*' && return 1; return 0 ;;
  esac
  return 1
}

for SEG in "${SEGMENTS[@]}"; do
  # ცარიელი სეგმენტი (მაგ. '&&'-ის მეორე '&') გამოტოვე
  read -r -a ARGS <<< "$SEG"
  [ ${#ARGS[@]} -eq 0 ] && continue
  # წინ მდგომი env ცვლადები (CI=true cmd) — თავად ბრძანება მაინც მოწმდება
  while [ ${#ARGS[@]} -gt 0 ] && [[ "${ARGS[0]}" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]]; do ARGS=("${ARGS[@]:1}"); done
  [ ${#ARGS[@]} -eq 0 ] && continue
  CMD="${ARGS[0]}"
  case "$CMD" in
    cd|pwd|ls|cat|head|tail|wc|grep|egrep|fgrep|rg|sort|uniq|cut|tr|file|stat|tree|which|basename|dirname|realpath|echo|true) ;;
    find)
      for bad in '-exec' '-execdir' '-delete' '-ok' '-okdir' '-fprint*' '-fls'; do has_arg "$bad" && block "find $bad"; done ;;
    git) check_git ;;
    npm|pnpm)
      if [ "${ARGS[1]}" = audit ]; then
        has_arg 'fix' && block "$CMD audit fix"; has_arg '--fix' && block "$CMD audit --fix"
      elif [ "${ARGS[1]}" = ls ]; then :
      else check_tests || block "$CMD ${ARGS[1]}"
      fi ;;
    pip-audit) has_arg '--fix' && block "pip-audit --fix" ;;
    *) check_tests || block "$CMD" ;;
  esac
done
exit 0
