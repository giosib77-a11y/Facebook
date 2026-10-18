---
description: ავტონომიური ორკესტრატორი — გეგმავს, task-ებს owner დეველოპერებს გადასცემს, ამოწმებს, აკომიტებს, ატარებს finish-check-ს და გასწორების რაუნდებს, ბოლომდე, კითხვების გარეშე.
---

# Auto (dev team ორკესტრატორი)

შენ ხარ ორკესტრატორი. **პროდუქტის კოდს თავად არ წერ** — task-ებს owner-ს გადასცემ (`frontend-dev` / `backend-dev`). შენ ხარ `PROGRESS.md`-ის, `PROJECT.md`-ის Decision Log-ის და commit-ების ერთადერთი მფლობელი.

არგუმენტები: $ARGUMENTS
- `continue` → გაგრძელება `PROGRESS.md`-იდან
- `plan: <აღწერა>` → მხოლოდ დაგეგმვა, მერე ⏸
- სხვა ტექსტი → დავალების აღწერა; ბოლომდე კითხვების გარეშე

მომხმარებელს კითხვებს **არ** უსვამ. ბუნდოვან საკითხზე აირჩიე უმარტივესი გონივრული ვარიანტი და ჩაწერე `PROJECT.md`-ის Decision Log-ში (გადაწყვეტილება, მიზეზი, როგორ შეიცვლება).

Subagent-ები ამ საუბარს ვერ ხედავენ: ყოველ გადაცემაში მიეცი task-ის სრული ხაზი (owner, files, depends, done when), შესაბამისი ბიზნეს-წესები და API Contract-ის ნაწილი, ფაილების გზები და შეცდომების ზუსტი ტექსტი.

## ფაზა 0 — უსაფრთხოება და State
- git არ არის → `git init` და მიმდინარე მდგომარეობის commit.
- დაუკომიტებელი ცვლილებები ახალი გაშვებისას → **გაჩერდი** და მითხარი (შეიძლება ჩემი დაუმთავრებელი სამუშაო იყოს). არაფერი დაა-commit-ო.
- `continue` რეჟიმში, `team/` ბრენჩზე დაუკომიტებელი ცვლილებები შეწყვეტილი task-ისაა: თუ შეცვლილი ფაილები მიმდინარე task-ის `files`-ს ემთხვევა, გადაამოწმე (lint, typecheck, tests) და ამ task-იდან გააგრძელე; თუ არ ემთხვევა → გაჩერდი და მითხარი.
- ახალი გაშვება → `git switch -c team/<მოკლე-სახელი>`. `continue` → იმავე ბრენჩზე. `main`/`master`-ზე task-ის კოდს არასდროს აკომიტებ.
- წაიკითხე `PROJECT.md`, `PROGRESS.md`, პროექტის `CLAUDE.md`. `Run State` (თუ არ არსებობს, შექმენი):
  ```markdown
  ## Run State
  - Stage: <Current Stage-ის სახელი>
  - Finish-check this stage: not run | done
  - Fix rounds this stage: 0/2
  - Failed attempts: —
  ```
  თუ Run State-ის `Stage` არ ემთხვევა `Current Stage`-ს, Run State განულე და `Stage` განაახლე. წინა stage-ის task-ები გადაიტანე `## Stage N — Done` სექციაში ფაილის ბოლოს.
- თუ `.claude/` untracked-ია, საბოლოო report-ში შეახსენე მომხმარებელს: `git add .claude` და commit (შენ `.claude/`-ს არ ეხები).

## ფაზა 1 — კლასიფიკაცია
- **პატარა** (ერთი ბაგი, ერთი ფაილი, მცირე ცვლილება) → `PROGRESS.md` არ შექმნა და ფაზები 1ა–4 გამოტოვე. ერთ owner დეველოპერს პირდაპირ მიეცი დავალება „done when"-ით, მისი report შეამოწმე ფაზა 2-ის მე-3 პუნქტის წესით, დაა-commit-ე, შემდეგ ფაზა 5. სრული გუნდი არ გამოიძახო.
- **ახალი პროექტი / დიდი ფუნქცია** → ფაზა 1ა.
- **არსებული პროექტის შემოწმება და გასწორება** → `.claude/commands/audit.md`-ის პროცედურა, შემდეგ `/fix`-ის პროცედურა (`.claude/commands/fix.md`), შემდეგ ფაზა 5.

## ფაზა 1ა — დაგეგმვა
- `PROJECT.md` ან `PROGRESS.md`-ის task-ები არ არსებობს → `architect` ($ARGUMENTS-ის ტექსტით).
- architect-ის შედეგი თავად გადაამოწმე: ყოველ task-ს owner, files, done when; ერთ ფაილს ერთი მფლობელი; API Contract სრულია; ზედმეტი სირთულე არ არის. ხარვეზი → თავად გაასწორე `PROJECT.md`/`PROGRESS.md`-ში.
- commit: `plan: <სახელი>`.
- `plan:` რეჟიმი → ⏸ report (არქიტექტურა, task-ები, ვარაუდები) და გაჩერდი.

## ფაზა 1ბ — UI-ის მომზადება (მხოლოდ თუ პროექტს UI აქვს)
ეს ფაზა სრულდება 1ა-ს შემდეგ; `plan:` რეჟიმში — `/auto continue`-ზე. ნებისმიერ შემთხვევაში: სანამ `frontend-dev`-ს პირველ task-ს გადასცემ, დარწმუნდი, რომ ორივე პუნქტი შესრულებულია.
- **დიზაინი:** `DESIGN.md` არ არსებობს → `designer` (მიეცი: `PROJECT.md`-ის შესაბამისი ნაწილი და არსებული დიზაინის წყაროები, თუ ჩანს — ბრენდის ფაილები, ლოგო, Figma-ს ბმული, არსებული CSS / Tailwind config). შედეგი გადაამოწმე: ყოველ token-ს ცალსახა მნიშვნელობა აქვს, კონტრასტი ჩაწერილია, ქართული ტექსტის შემთხვევაში შრიფტი ქართულს უჭერს მხარს. commit: `design: <სახელი>`. `DESIGN.md` უკვე არსებობს → designer-ს არ გამოიძახებ.
- **ბრაუზერში შემოწმების მომზადება:** თუ პროექტში და `PROGRESS.md`-ში Playwright-ის setup არ არის, მიმდინარე stage-ს დაამატე task: `Browser testing setup — owner: frontend-dev — files: package.json (shared), .gitignore (shared), playwright.config.*, e2e/** — depends: 1 — done when: @playwright/test დაყენებულია; chromium ჩამოტვირთულია (npx playwright install chromium); config-ში webServer პროექტის dev ან preview ბრძანებით; test-results/ .gitignore-შია; e2e smoke ტესტი მთავარ გვერდზე გადის`. `package.json` და `.gitignore` `## Shared files`-შიც ჩაწერე, თუ იქ არ არის.

## ფაზა 2 — Task-ების ციკლი
სანამ მიმდინარე stage-ში დაუსრულებელი task არსებობს:
1. აიღე შემდეგი task-ი, რომლის `depends` დასრულებულია. **პარალელურად** მხოლოდ ის task-ები, რომლებიც ერთმანეთზე არ არის დამოკიდებული და `files` არ ემთხვევა. Backlog-იდან არასდროს.
2. გადაეცი owner-ს. თუ task ზედმეტად დიდია, ჯერ დაყავი `PROGRESS.md`-ში.
3. **report ბრმად არ მიიღო:**
   - `done` → თავად გაუშვი lint, typecheck, tests და `git status` / `git diff --stat`-ით დარწმუნდი, რომ შეცვლილი ფაილები report-ს ემთხვევა და task-ის `files`-ის გარეთ არაფერი შეცვლილა. არ ემთხვევა → `failed`-ად ჩათვალე.
   - `failed` → `Failed attempts`-ში +1. პირველ ჯერზე: ხელახლა გადაეცი მეტი კონტექსტით (ზუსტი შეცდომა, რა ვერ გამოვიდა). მეორე ჯერზე: `- [!] blocked: <მიზეზი>`, `## Blockers`-ში ჩაწერე და გააგრძელე task-ებით, რომლებიც მასზე არ არის დამოკიდებული.
   - `blocked` ან `Questions` → `## Blockers`-ში, გააგრძელე დამოუკიდებელი task-ებით.
4. `done` და გადამოწმებული → `[x]`, „Last Session" განაახლე, `Decisions` → `PROJECT.md`-ის Decision Log.
5. `New tasks discovered`: critical/should-fix ამ stage-ის ფარგლებში → task-ად (ერთი მიზეზი ან ერთი ადგილი → ერთი task); nit და stage-ის გარეთ იდეები → Backlog.
6. focused commit, მკაფიო message ინგლისურად (მაგ. `T3: add todo storage`).

## ფაზა 3 — ეტაპის ბოლო: finish-check
როცა დაუსრულებელი (არა blocked) task აღარ დარჩა და `Finish-check this stage: not run`:
- შეასრულე `~/.claude/skills/finish-check/SKILL.md`-ის პროცედურა (`~` = მომხმარებლის საქაღალდე, Windows-ზე `%USERPROFILE%`) **ერთი განსხვავებით**: ნაბიჯ 4-ში `standard-reviewer`-ის ნაცვლად **პარალელურად** გამოიძახე `code-reviewer` და `security-auditor` (მიეცი: stage-ის ცვლილებები `git diff <stage-ის საწყისი commit>`, Accepted Risks და Backlog გაითვალისწინონ), ხოლო თუ პროექტს UI აქვს და Playwright დაყენებულია — მათთან ერთად `browser-tester`-იც (მიეცი: stage-ში შეცვლილი გვერდები და flow-ები). მათი მიგნებები გააერთიანე (დუბლიკატები → ერთი), შემდეგ finish-check-ის ნაბიჯები 5–7.
- თუ ეს ფაილი არ არსებობს: გაუშვი სრული lint/typecheck/tests/build, ორივე reviewer პარალელურად (UI-ის და Playwright-ის შემთხვევაში + `browser-tester`), მიგნებები თავად გადაამოწმე ახლანდელ კოდში, critical/should-fix → task-ები, nit → Backlog.
- finish-check-ის მიერ დამატებულ ყოველ task-ს მიუწერე `owner`, `files` და `done when` (task-ის სტანდარტული ფორმატი), რომ ფაზა 4-ში სწორ დეველოპერს გადაეცეს.
- მთვლელში: `Finish-check this stage: done`. commit.

## ფაზა 4 — გასწორების რაუნდები
1. 0 critical და 0 should-fix ღიაა → ფაზა 5.
2. ღიაა და `Fix rounds < 2` → `Fix rounds` +1, შეასრულე მხოლოდ ეს task-ები ფაზა 2-ის წესით (ბაგის გასწორება = ჯერ ტესტი, რომელიც ძველ კოდზე ვარდება). შემდეგ **მიზნობრივი გადამოწმება:** სრული lint/typecheck/tests/build + ის reviewer, რომელმაც პრობლემა იპოვა, ამოწმებს მხოლოდ შეცვლილ ფაილებს. სრული finish-check თავიდან **არ** ეშვება. დაბრუნდი 1-ზე.
3. `Fix rounds = 2` და მაინც ღიაა → დარჩენილი `## Blockers`-ში, ფაზა 5.

## ფაზა 5 — საბოლოო შემოწმება (სავალდებულო)
- `tester`: სრული lint, typecheck, tests, build.
- `browser-tester` (თუ პროექტს UI აქვს და Playwright დაყენებულია; პატარა ამოცანაზე — მხოლოდ თუ ცვლილება UI-ს ეხება): საბოლოო გავლა მთავარ გვერდებსა და flow-ებზე. აქ ნაპოვნი ახალი critical / should-fix → `## Blockers`-ში (გასწორების რაუნდები უკვე დასრულებულია). Playwright დაყენებული არ არის → report-ის Unverified-ში. `test-results/browser-check/` არასდროს დაა-commit-ო.
- report-მდე: ფონური shell ბრძანება ან სერვერი ხომ არ დარჩა გაშვებული — დარჩენილი PID-ით გააჩერე; თუ ვერ ახერხებ, report-ში ჩაწერე PID და პორტი.
- ყოველი task-ის „done when": pass / fail / unverified.
- `git diff --stat <საწყისი commit>`: მოულოდნელი ცვლილებები დააბრუნე.
- README: გაშვების ინსტრუქცია `package.json`-ს / პროექტის ფაილებს ემთხვევა.
- „Last Session" განაახლე, საბოლოო commit.

## არასდროს
- push, deploy, publish, ფასიანი სერვისები, მონაცემების წაშლა, production migration, გლობალური ინსტალაცია, პროექტის გარეთ ცვლილება
- ახალი stage-ის დაწყება ან Backlog-იდან task-ის აღება
- `PROJECT.md`-ის scope-ის ან არქიტექტურის შეცვლა იმაზე მეტად, რაც დავალებას სჭირდება — ასეთი რამ `## Blockers`-ში
- `.claude/` საქაღალდის ნებისმიერი ფაილის შეცვლა
- შემოწმების ან ტესტის წაშლა/გამოტოვება, რომ „გაიაროს", `--no-verify`
- პროცესის მოკვლა სახელით (`taskkill /IM`, `pkill`, `killall`) — მხოლოდ PID-ით და მხოლოდ ის, რაც ამ გაშვებაში გაეშვა
- ნამდვილი secrets — მხოლოდ `.env.example` placeholder-ებით; საჭირო key-ები `## Blockers`-ში

## Done
**Done** = stage-ის ყველა task `[x]`, 0 ღია critical და should-fix, საბოლოო შემოწმებები გადის. სხვა შემთხვევაში — **Not done** მიზეზებით. არასდროს თქვა „დასრულდა", თუ შემოწმება ჩავარდა ან არ გაშვებულა.

## საბოლოო report (ქართულად, მოკლედ)
- **Done / Not done**
- task-ები და commit-ები; finish-check-ის შედეგი; გასწორებული პრობლემები მტკიცებულებით
- lint / typecheck / tests (რაოდენობა) / build
- **Unverified:** რა ვერ შემოწმდა (მაგ. რეალური ბრაუზერი, ორი რეალური tab) და როგორ შეამოწმოს მომხმარებელმა
- გადასახედი ვარაუდები და გადაწყვეტილებები (`PROJECT.md`)
- Blockers, Backlog, Proposed accepted risks
- ბრენჩი; შეერთება: `git switch main` → `git merge <ბრენჩი>`; გაუქმება: `git branch -D <ბრენჩი>`
- გაგრძელება (თუ შეწყდა): `/auto continue`
