# DESIGN.md — ChatAssist (არსებული "emerald" დიზაინის დოკუმენტაცია)

ეს ფაილი აღწერს **არსებულ** დიზაინს, ახალს არაფერს ამატებს. წყაროები: `frontend/styles.css` (პანელი, ადმინი, reset),
`frontend/order.css` (შეკვეთის გვერდი), `frontend/landing.css` (landing), `<style>` ბლოკი `frontend/admin.html`-ში,
inline `style={{}}` JSX-ში. `(დამატებულია)` = ახალი, მხოლოდ არსებული token-ებით შედგენილი სპეციფიკაცია.
CSS ფაილებში ცვლადების სახელები განსხვავდება (იხ. §2), მნიშვნელობები — იდენტურია. Dark mode არ არსებობს.

## 1. მიმართულება
სუფთა, ღია SaaS სტილი: მწვანე-ზურმუხტის accent, თეთრი ბარათები მქრქალ მწვანე-ნაცრისფერ ფონზე, მომრგვალებული კუთხეები,
რბილი მწვანედ შეფერილი ჩრდილები. ტონი — მეგობრული, ქართულენოვანი, emoji იკონებად. ვერიდებით მკვრივ/მუქ ინტერფეისს.

## 2. ფერები
CSS ცვლადები: `styles.css` `:root` (panel/admin/reset) · `order.css` (`--brand*`, `--ink`, `--line`) · `landing.css` (`--brand*`, `--ink`, `--line`, `--bg-soft`).

| Token (panel / order+landing) | Hex | გამოყენება |
|---|---|---|
| `--bg` / `--bg` (landing: `--bg-soft`) | `#f4f8f6` | გვერდის ფონი (landing-ზე `--bg` = `#ffffff`) |
| `--card` | `#ffffff` | ბარათი, input, modal |
| `--text` / `--ink` | `#10231b` | ძირითადი ტექსტი |
| `--muted` | `#5f7268` | მეორადი ტექსტი, label |
| `--primary` / `--brand` (= `--ok`) | `#059669` | accent, ბმული, focus border, success |
| `--primary-2` / `--brand-2` | `#10b981` | gradient-ის ღია ბოლო |
| `--primary-dark` / `--brand-dark` | `#047857` | active tab ტექსტი, MRR gradient ბოლო |
| `--primary-light` / `--brand-light` | `#e7f7ef` | tint ფონი, focus ring, active tab |
| `--primary-grad` / `--brand-grad` | `linear-gradient(135deg,#10b981 0%,#059669 100%)` | primary ღილაკი, brand-mark, active `.tab` |
| `--border` / `--line` | `#e3ece7` | ყველა საზღვარი/გამყოფი |
| `--danger` | `#dc2626` | შეცდომა, danger ღილაკი, toast-err |
| `--ok` | `#059669` | წარმატება, toast-ok |

Hard-coded (token-ის გარეშე, ისე გამოიყენება როგორც არის):
- warning: `#f59e0b` (attention border), `#d97706` (near-limit, order-processing, stock-low), `#b45309` (attention h2), `#fffbeb` (attention bg)
- alert/ნარინჯისფერ-წითელი: `#c2410c` (alert ტექსტი), `#fff6f3` bg, `#f6cfc3` border, `#fde3da` icon bg
- tier-lock: bg `#fff7ed`, border `#fed7aa`, text `#9a3412`
- badge-on bg `#dcfce7`; badge-off bg `#fee2e2`; pill-off bg `#f1f5f9`; led off `#cbd5c9`; skeleton `#e8edf3`; usage-bar track `#e2e8f0`
- term-chip `#eef2ff` / `#4338ca`; cancelled order `#94a3b8`; chart teal `#14b8a6`; ghost-hover border `#cbd5e1`; modal overlay `rgba(15,23,42,.5)`
- landing: `--ring: 0 0 0 4px rgba(5,150,105,.16)`

### კონტრასტი (WCAG 2.x, გამოთვლილი)
| წყვილი | თანაფარდობა | AA |
|---|---|---|
| `#10231b` / `#f4f8f6` (ტექსტი/ფონი) | 15.34 | კი |
| `#10231b` / `#ffffff` | 16.43 | კი |
| `#5f7268` / `#ffffff` (muted/ბარათი) | 5.13 | კი |
| `#5f7268` / `#f4f8f6` | 4.79 | კი |
| `#5f7268` / `#e7f7ef` | 4.63 | კი |
| `#5f7268` / `#f1f5f9` (pill-off) | 4.68 | კი |
| `#ffffff` / `#059669` (primary ღილაკი, ბოლო gradient წერტილი; toast-ok) | **3.76** | **არა** (ნორმ. ტექსტი); დიდ/bold ≥18.66px — კი |
| `#ffffff` / `#10b981` (gradient-ის ღია ბოლო) | **2.54** | **არა** |
| `#ffffff` / `#047857` | 5.48 | კი |
| `#ffffff` / `#dc2626` (toast-err, danger hover) | 4.83 | კი |
| `#dc2626` / `#ffffff` (danger ღილაკის ტექსტი) | 4.83 | კი |
| `#dc2626` / `#f4f8f6` | 4.51 | კი (ზღვარზე) |
| `#059669` / `#ffffff` (ბმული, `.fb-connected`, `.import-ok`) | **3.76** | **არა** |
| `#059669` / `#e7f7ef` (`.ov-ch .s.yes`) | **3.40** | **არა** |
| `#047857` / `#e7f7ef` (active tab) | 4.95 | კი |
| `#059669` / `#dcfce7` (badge-on, ok-badge) | **3.43** | **არა** |
| `#dc2626` / `#fee2e2` (badge-off) | **3.95** | **არა** |
| `#b45309` / `#fffbeb` (attention h2) | 4.84 | კი |
| `#d97706` / `#ffffff` (near-limit ტექსტი) | **3.19** | **არა** |
| `#c2410c` / `#ffffff` | 5.18 | კი |
| `#c2410c` / `#fff6f3` (stat alert) | 4.86 | კი |
| `#9ca3af` / `#fffbeb` (attention `.product-meta` inline) | **2.45** | **არა** |
| `#9ca3af` / `#ffffff` (OrdersTab inline) | **2.54** | **არა** |
| `#9a3412` / `#fff7ed` (tier-lock) | 6.88 | კი |
| `#4338ca` / `#eef2ff` (term-chip) | 7.07 | კი |
| `#10231b` / `#fffbeb` | 15.85 | კი |
| `#dc2626` / `#fff6f3` | 4.53 | კი |

## 3. ტიპოგრაფია
- ჩატვირთვა: Google Fonts `@import` `styles.css`-ში და `order.css`-ში: **Inter** 400–800 + **Noto Sans Georgian** 400–800, `display=swap` (landing.css-ს `@import` არ აქვს — იხ. შეუსაბამობები). ორივე უფასო, SIL OFL 1.1.
- Stack: `"Inter", "Noto Sans Georgian", -apple-system, "Segoe UI", Roboto, sans-serif`.
- **ქართულის მხარდაჭერა: კი, Noto Sans Georgian-ით.** Noto Sans Georgian მოიცავს Mkhedruli-ს (Fontsource: ka, 225 glyph). Inter-ს ქართული ანბანი არ აქვს (Google Fonts-ის Inter subset-ებში ქართული არ არის; ვერ დავადასტურე ძიებით), ამიტომ ქართული სიმბოლოები ბრაუზერის მიერ ავტომატურად `Noto Sans Georgian`-ზე გადადის — ეს სწორად მუშაობს. ბოლო fallback-ები (`-apple-system`, `Segoe UI`, `Roboto`) ქართულს ასევე ფარავს ძირითად OS-ებზე.
- `body`: line-height 1.5 (landing 1.6), `-webkit-font-smoothing: antialiased`.
- Weights: 400 ტექსტი, 600 ღილაკი/label/badge, 700 აქცენტი/active tab, 800 brand/სტატისტიკა.
- ზომები (rem): .72 badge/chip-label · .74–.78 stat label, footer · .8–.85 hint, meta, btn-sm, table th · .88–.9 label, table, auth · 1 (16px) body, input, .btn · 1.05 h2, brand · 1.3–1.5 h1 (order), stat value 1.45 · 1.7 admin stat/summary · landing hero `clamp(2.1rem,4.6vw,3.35rem)`, line-height 1.1.
- letter-spacing: `-.01em` brand/h2, `-.02em` stat/h1, `-.03em` hero.

## 4. დაშორებები და layout
- Spacing (px, რეალურად გამოყენებული): 4, 6, 8, 10, 12, 14, 16, 18, 20, 24. Gap ტიპიურად 8/10/12/16; ბარათის padding 18 (order mobile ≤420px: 15); გვერდითი padding 16.
- Container: `.container` max-width **1120px** (landing `--max` 1120px, padding 0 20px); order გვერდი `.order-wrap` max-width **600px**; modal 720px; auth-card 410px.
- Dashboard: grid `216px 1fr`, gap 20; sidebar sticky `top: 78px`; stat-cards 4 სვეტი (≤560px: 2); `.two-col` `1.3fr 1fr` (≤720px: 1 სვეტი); admin `.stat-grid` 4 სვეტი (≤700px: 2).
- Breakpoints (max-width): 420 (order), 480 (panel mobile), 560 (stat-cards, landing), 700 (admin stat-grid), 720 (two-col), **820 (sidebar → ზედა horizontal tabs)**, 900 (landing). მობილური ~390px და desktop ≥1280px ორივე ამ წესებით იფარება.
- Header: sticky top, `rgba(255,255,255,.82)` + `backdrop-filter: blur(10px)`, border-bottom, z-index 10.
- Z-index: header 10 · landing nav 50 · toast 100 · modal 200.

## 5. ფორმები (radius, საზღვარი, ჩრდილი)
- Radius: `--radius` **16px** (ბარათი; landing 18px) · 14 stat-card/tabs-nav · 12 product-item/ov-ch/mapping · 10 input, `.btn`, tab-btn · 8 `.tab`, icon-btn, select-small · 999 badge/pill/chip/usage-bar · 50% led/ok-badge.
  order.css: input 11px, `.btn` 12px, product-item 13px.
- Საზღვარი: `1px solid var(--border)`; attention-card `4px` მარცხნივ; order-item `border-left-width:4px` (new `#059669`, processing `#d97706`, done `#059669`, cancelled `#94a3b8`); summary (order) `1.5px solid var(--brand)`.
- `--shadow-sm: 0 1px 2px rgba(16,40,30,.05), 0 3px 12px rgba(16,40,30,.05)` (ბარათი, stat)
- `--shadow-md: 0 8px 20px -10px rgba(6,95,70,.18), 0 18px 44px -22px rgba(6,95,70,.20)` (auth-card, modal, product-item hover; order.css: `.2`)
- primary ღილაკი: `0 8px 20px -8px rgba(5,150,105,.55)`, hover `0 14px 28px -10px rgba(5,150,105,.7)`; toast: `0 4px 16px rgba(0,0,0,.15)` (order: `0 8px 24px rgba(0,0,0,.18)`).

## 6. კომპონენტები (`styles.css`, თუ სხვა არ არის მითითებული)
**ღილაკი `.btn`** — `padding 12px 16px; radius 10; weight 600; border 1px transparent`; `.btn-sm` `8px 12px; .85rem`.
- `.btn-primary`: gradient bg, ტექსტი `#fff`; hover `translateY(-1px)` + დიდი ჩრდილი + `saturate(1.06)`; active `translateY(0/1px)`.
- `.btn-ghost` (მეორადი): bg `#fff`, border `--border`, ტექსტი `--text`; hover bg `--bg`, border `#cbd5e1`.
- `.btn-danger`: transparent bg, ტექსტი+border `--danger`, `padding 8px 12px`; hover bg `--danger`, ტექსტი `#fff`.
- disabled: `styles.css`-ში **არ არის განსაზღვრული** (მხოლოდ `order.css`: `.btn-primary:disabled {opacity:.55; cursor:default; box-shadow:none; filter:none}`). Admin-ში `disabled` გამოიყენება ბრაუზერის default-ით.
- loading: `.btn.is-loading` — ტექსტი transparent, `pointer-events:none`, 16px spinner (`::after`, 2px border, `.6s linear`); ghost/danger-ზე spinner ფერი `#059669`.
- focus: ღილაკს საკუთარი focus ring არ აქვს (ბრაუზერის default outline).
- `.icon-btn` (admin): `5px 9px; radius 8; border --border; bg #fff`; `.danger` — `--danger` ტექსტი/border, hover ივსება.
- `.tab-btn-link`: ტექსტური ბმული-ღილაკი, `--primary`, 600, `.82rem`; hover underline.

**Input/select/textarea** — `padding 12px; border 1px --border; radius 10; bg #fff; font inherit; width 100%`. Focus: `outline:none; border-color --primary; box-shadow 0 0 0 3px --primary-light`. `label`: column, gap 6, `.9rem`, `--muted`. Disabled/error სტილი CSS-ში არ არის; ვალიდაციის შეცდომა = toast-err ან `--danger` ტექსტი (`.import-err`).

**ბარათი `.card`** — bg `--card`, border, radius 16, padding 18, `--shadow-sm`, margin-bottom 16 (`.dash-main .card` margin 0, gap 16). `.attention-card`: `border-color #f59e0b; border-left 4px solid #f59e0b; bg #fffbeb`, `h2` ფერი `#b45309`.
**StatCard `.stat-card`** (Dashboard): bg `--card`, border, radius 14, padding `14px 15px`; `.si` 34×34 icon box (`--primary-light`, radius 10); `.sv` 1.45rem/800; `.sl` .74rem `--muted`. `.stat-card.alert`: border `#f6cfc3`, bg `#fff6f3`, `.si` `#fde3da`, `.sv` `#c2410c`. Admin: `.stat` (radius 12, padding 16, `.val` 1.7rem/800), `.stat.mrr` — gradient `#10b981→#047857`, ტექსტი `#fff`, `.lbl` `rgba(255,255,255,.85)`.
**Badge `.badge`** (panel): `.72rem; 600; padding 2px 9px; radius 999`; `.badge-on` (`#dcfce7`/`--ok`), `.badge-off` (`#fee2e2`/`--danger`). **Pill `.pill`** (admin.html inline): იგივე ზომა; `.pill-on` (= badge-on), `.pill-off` (`#f1f5f9`/`--muted`). `.term-chip`: indigo chip, `.85rem`.
**Led `.ov-bot .led`**: 9×9, radius 50%; `.on` bg `--ok` + `box-shadow 0 0 0 4px --primary-light`; `.off` bg `#cbd5c9`. კონტეინერი `.ov-bot`: flex, gap 10, `padding 11px 12px`, border, radius 12, bg `--bg`; `b` .85rem, `span` .75rem `--muted`.
**ნავიგაცია** — desktop: `.tabs-nav` sidebar (column, bg card, border, radius 14, padding 8); `.tab-btn` `padding 11px 13px; .92rem/600; --muted`, hover bg `--bg`, `.active` bg `--primary-light`, ტექსტი `--primary-dark`, 700. ≤820px: row + `overflow-x:auto`, `.tab-btn` nowrap. Header `.app-header` + `.brand` (brand-mark 30×30 radius 9). Auth `.tabs`/`.tab` (`.tab.active` gradient + `#fff`).
**ცხრილი `table.admin`** (admin.html): `.9rem`; th `.82rem/600 --muted`; td/th `padding 10px 12px; border-bottom 1px --border; nowrap; left`; row hover td bg `--bg`; wrapper `.admin-table-wrap {overflow-x:auto}`. `select.tier-sel` `width:auto; padding 6px 8px; radius 8; .85rem`. მოქმედებები `.row-actions` (gap 6). ზღვრის გადამეტება: inline `color:var(--danger); font-weight:600`.
**Toast `.toast`** — fixed `top:16; left:50%`; `padding 12px 18px; radius 10; ტექსტი #fff; z 100; max-width 90vw`. `.toast-ok` bg `--ok`, `.toast-err` bg `--danger`. (order: radius 12, weight 500.)
**Alert/hint ბლოკები**: `.tier-lock` (ნარინჯისფერი ინფო), `.import-hint` (.85rem muted), `.import-result.import-ok/-err` (ტექსტი `--ok`/`--danger`), `.usage-upgrade.pending` (`#d97706`). ცალკე banner კომპონენტი არ არსებობს.
**Modal** (admin): overlay `rgba(15,23,42,.5)`, `.modal` bg `#fff`, radius 16, max-width 720, padding 20, `--shadow-md`.

## 7. გვერდის მდგომარეობები
- Loading: skeleton `.skel-item` > `.skel` (bg `#e8edf3`, radius 6, shimmer 1.3s) ხაზები `.skel-line` (13px; `.lg` 55%/15px; `.sm` 32%); ღილაკზე — `is-loading`; admin-ში ტექსტი `იტვირთება...` (`.import-hint`).
- Empty: `.empty-state` (centered, `--muted`, padding 16) ან `.ov-empty` (.85rem `--muted`), ქართული ერთი წინადადება ("შეკვეთები ჯერ არ არის.").
- Error: toast-err (`toast(msg, true)`); სრული გვერდი — ბარათი centered + `h2` ფერი `--danger` ("წვდომა აკრძალულია"). ფორმაში — `.import-err`.

## 8. სურათები და იკონები
- იკონები: **emoji** (ტექსტში/სათაურებში, 🔔 🤖 🧾 📦 ✓ ↻ 🗑 ...); icon ნაკრები/ბიბლიოთეკა არ გამოიყენება. ლოგო: `frontend/public/favicon.svg`; `.brand-mark` 30×30 gradient კვადრატი.
- პროდუქტის thumbnail `.product-thumb` 50×50 radius 11 `object-fit:cover`, bg `--bg`; preview `.img-preview img` 96×96 radius 12; ფოტოს გარეშე — placeholder არ არის (ბარათი უბრალოდ ტექსტით). `public/`: `config.js`, `favicon.svg`, `sample-products.csv/.xlsx`.

## 9. Stage 20 კომპონენტები `(დამატებულია)`
მხოლოდ ზემოთ აღწერილი token-ები; ახალი ფერი არ შემოდის. Warning = `#f59e0b` border / `#fffbeb` bg / `#b45309` სათაური / ძირითადი ტექსტი `--text`.

1. **Warning badge "⏸ ბოტი შეჩერებულია · HH:MM-მდე"** — `.badge` ზომით (`.72rem/600`, radius 999, `2px 9px`), bg `#fffbeb`, ტექსტი `#b45309` (4.84), `border:1px solid #f59e0b`. ადგილი: `.product-meta`-ის გვერდით `AttentionCard`-ის `.product-item`-ში (`src/panel/Dashboard.jsx`). **"▶ ბოტის ჩართვა"** — `.btn .btn-ghost .btn-sm` იმავე `.product-actions`-ში, ✓ მოგვარდა (`btn-primary btn-sm`)-ის გვერდით.
2. **"🗑 კლიენტის მონაცემების წაშლა"** — `.btn .btn-danger` (ზომა: `.btn-sm`); transparent, `--danger` ტექსტი/border (4.83), hover ივსება `--danger`/`#fff`. loading: `is-loading`. დადასტურების დიალოგი — არსებული `confirm()` სტილით, როგორც admin `delShop`.
3. **Banner-ები** — ახალი ზოგადი კლასი `.banner` (padding `12px 14px`, radius 12, `.9rem`, border 1px + `border-left 4px`), `--text` ტექსტი. ≤3 დღე (warning): იგივე სტილი რაც `.attention-card` (`#fffbeb`/`#f59e0b`), სათაური `#b45309` 700. ამოწურული (error): bg `#fff6f3`, border `--danger`, სათაური `--danger` 700 (4.53). ბანერის ბოლოს `.btn .btn-primary .btn-sm` "განაახლე პაკეტი" (არსებული upgrade flow-ს `.usage-upgrade` ბლოკთან ერთად, `Dashboard.jsx`). არსებული ანალოგი: `.tier-lock`, `.stat-card.alert`.
4. **Neutral badge "📭 email შეტყობინებები გამორთულია"** — `.badge` + bg `#f1f5f9`, ტექსტი `--muted` (4.68) = `.pill-off`-ის სტილი (panel-ში ცალკე კლასი უნდა გამოცხადდეს `styles.css`-ში, რადგან `.pill-off` მხოლოდ admin.html-შია).
5. **Bot health warning** — `Overview`-ის `.ov-bot` ბლოკში (`Dashboard.jsx`): led — `.led.off`-ის ზომა, ფერი `#d97706` (არ არის კლასი; ახალი `.led.warn`); ბოლო `span` ხაზი ტექსტით ფერი `#c2410c` (5.18 თეთრზე / 4.84 `--bg`-ზე), `.75rem`, weight 600. ტექსტები: token შეცდომა / გაგზავნა ვერ მოხერხდა / ბიუჯეტი ამოიწურა. წითელი (`--danger`) — მხოლოდ ბიუჯეტის ამოწურვაზე, თუ ბოტი სრულად ჩერდება.
6. **Admin ცხრილი, სვეტი "ვადა"** — `table.admin` (admin.html), ახალი `<th>ვადა</th>` "პაკეტის" შემდეგ; თარიღი `fmtDate`-ით. ≤3 დღე ან ამოწურული: `color:var(--danger); font-weight:600` (იგივე ნიმუში, როგორც `over` ლიმიტზე; 4.83 თეთრზე / 4.51 hover-ზე). **"+30 დღე"** — `.icon-btn` (ან `.btn .btn-ghost .btn-sm`) `.row-actions`-ში, ზომა `.85rem`.
7. **Admin LLM spend alert** — banner `.banner` warning (`#fffbeb`/`#f59e0b`/`#b45309` სათაური) ბარათების თავზე `AdminPage.jsx`-ში, `.stat-grid`-ამდე; ზღვრის გადაჭარბებისას error-ვარიანტი (`#fff6f3`/`--danger`).

## 10. შეუსაბამობები არსებულ CSS-ში (არ გასწორებულა)
- Primary ღილაკი/toast-ok: თეთრი `#fff` ტექსტი `#059669`-ზე = 3.76, gradient-ის ღია ბოლოზე 2.54 → AA-ს ვერ აკმაყოფილებს ნორმალურ ტექსტზე. იგივე: `--primary` ბმული თეთრზე (3.76), badge-on (3.43), badge-off (3.95), `.ov-ch .s.yes` (3.40), `#d97706` ტექსტი (3.19), `#9ca3af` inline meta (2.45–2.54).
- ერთი და იგივე token-ები სხვადასხვა სახელით: `--primary/--text/--border/--card` (styles.css) vs `--brand/--ink/--line` (order/landing); landing-ს `--bg` = `#fff`, სხვაგან `#f4f8f6`.
- `.btn` სამ ადგილას სხვადასხვაა: padding 12/16, radius 10 (styles) · 15/20, radius 12, width 100%, 700 (order) · 12/22, radius 12, inline-flex (landing); `.card`/`.toast` radius და shadow-ც განსხვავდება.
- `.btn:disabled`, ღილაკის `:focus-visible` და input error/disabled სტილი `styles.css`-ში არ არის. Focus ring `--primary-light` (`#e7f7ef`) თეთრზე ~1.1:1 — ვიზუალურად სუსტია (მხოლოდ border-color ეხმარება).
- `.badge` (panel) და `.pill` (admin.html inline) — ორი ერთნაირი კომპონენტი; `.pill-off` panel-ში არ არსებობს. admin-ის სტილები (`.stat`, `table.admin`, `.modal`, `.icon-btn`, chart) inline `<style>`-შია, არა CSS ფაილში.
- `landing.css`-ს Google Fonts `@import` არ აქვს, მაგრამ იგივე font stack-ს იყენებს (ჩატვირთვა დამოკიდებულია `landing.html`-ზე).
- hard-coded ფერები token-ების ნაცვლად (`#d97706`, `#c2410c`, `#f59e0b`, `#9ca3af`, slate/gray ტონები `#334155`, `#475569`, `#6b7280`, `#94a3b8`) და inline `style={{color:"#9ca3af"}}`, `{color:"#d97706"}` JSX-ში.
- `.usage-downgrade:hover` იყენებს `#dc2626` პირდაპირ (`--danger`-ის ნაცვლად); chart legend `#14b8a6` ხელით.
- `.ov-bot` ბარათის არჩევა `.ov-bot span` — selector ეხება ყველა `span`-ს ბლოკში (ახალი inline ელემენტები მემკვიდრეობით მიიღებენ `.75rem muted`).
