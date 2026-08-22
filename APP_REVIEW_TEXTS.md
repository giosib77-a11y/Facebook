# App Review — მზა ტექსტები (ChatAssist)

Meta App Review-ს გასაგზავნი ინგლისური ტექსტები. ყველა ბლოკი მზაა ჩასაკოპირებლად.
სად რომელი ჩადის — იხ. ცხრილი ბოლოს.

---

## 1. ვიდეოს აღწერა (English) — ვიდეოსთან ერთად ჩასაწერი ტექსტი

> ვიდეოში წარწერად კი არა — Meta-ს ველში ტექსტად, ვიდეოს გვერდით.

```
This video demonstrates the full ChatAssist flow: a shop owner logs into
their ChatAssist dashboard at chatassist.ge, clicks "Connect Facebook Page,"
logs in with Facebook and grants the requested permissions (view their Pages,
manage the Page's messages and metadata, access Business Manager Pages, and
Instagram messaging). The Page becomes connected and subscribed to the
messaging webhook. A customer then sends a message to the Page on Messenger,
and ChatAssist automatically replies with an AI-generated response —
demonstrating pages_messaging in action.
```

---

## 2. ნებართვების justification — თითო permission-ის ახსნა

> Meta-ში თითო ნებართვის გვერდზე „How will you use this permission?" ველში
> ჩააკოპირე შესაბამისი აბზაცი.

```
pages_show_list — ChatAssist uses pages_show_list to display the list of
Facebook Pages the shop owner manages, so they can choose which Page to connect
to our chatbot.

pages_messaging — ChatAssist uses pages_messaging to receive messages sent to
the connected Page and to send automated AI-generated replies on the Page's
behalf. This is the core function of the service.

pages_manage_metadata — ChatAssist uses pages_manage_metadata to subscribe the
Page to messaging webhooks, so it receives real-time message events and can
respond to customers.

business_management — ChatAssist uses business_management to access Pages
managed inside the owner's Business Manager (New Pages Experience), so
business-owned Pages can be connected.

pages_read_engagement — ChatAssist uses pages_read_engagement to read the Page's
basic info and its linked Instagram account during connection setup.

instagram_basic — ChatAssist uses instagram_basic to identify the Instagram
Business account linked to the connected Page, so the owner can enable the bot
on Instagram.

instagram_manage_messages — ChatAssist uses instagram_manage_messages to receive
and reply to Instagram Direct messages on the connected Instagram Business
account, the same automated support as on Messenger.
```

---

## 3. Reviewer test steps — განმხილველისთვის ინსტრუქცია

> Meta-ში „Provide step-by-step instructions" ველში.

```
1. Go to https://chatassist.ge and log in with the test credentials provided.
2. In the dashboard, click "Connect Facebook Page" and grant the permissions.
3. Select a Page to connect to ChatAssist.
4. Send a message to that Page in Facebook Messenger.
5. ChatAssist will automatically reply to the message with an AI response.
```

---

## სად ჩადის Meta-ს ფორმაში

| ტექსტი | სად |
|---|---|
| #1 ვიდეოს აღწერა | ვიდეოს ატვირთვის გვერდზე, notes/description ველი |
| #2 justification | თითო permission → „How will you use…" |
| #3 test steps | „Step-by-step instructions for reviewer" |
| სატესტო login | email + პაროლი → უნდა მიაწოდო (განმხილველი თვითონ ამოწმებს) |

---

## ⚠️ მნიშვნელოვანი

- **პირველ submit-ს რჩევაა მარტო Facebook-ით** გააკეთო (IG-ის უარყოფა რომ ავიცილოთ).
  მაშინ #2-ში **ბოლო ორი** (`instagram_basic`, `instagram_manage_messages`) **გამოტოვე** —
  მათ Live-ის მერე ცალკე დაამატებ (Instagram dev-რეჟიმში ვერ დემონსტრირდება).
- გასაგზავნი ვიდეო: **Video 2** (2026-08-11 16-08-14.mp4) — მკვეთრი, watermark-ის გარეშე,
  სრული ნაკადი (login → permission-ეკრანი → ბოტის პასუხი).
- App Review-ს წინაპირობა: **ი/მ → Business Verification** (ეს კარიბჭე ჯერ ღიაა).

---

## 🧹 submit-ამდე დასალაგებელი

- [ ] 💵 **Render → Starter tier ($7/თვე) — submit-ამდე, არა გაშვებისას.**
      უფასო tier 15 წუთი უმოქმედობის შემდეგ იძინებს და გაღვიძებას 30-60 წამი
      სჭირდება. Meta-ს განმხილველი საიტს **თავად გახსნის** (login, permission-ეკრანი,
      privacy-გვერდი) — თუ იმ მომენტში ჩაძინებულია, განხილვა შეიძლება უარყოფილ იქნას
      და ხელახლა შეტანა კვირებს ნიშნავს.
      რიგითობა: ი/მ → Business Verification → **$7 tier** → submit → Live.
- [ ] **Meta → Facebook Login → Valid OAuth Redirect URIs**: მოხსენი
      `https://vividly-ideally-violet.ngrok-free.dev/facebook/connect/callback`
      (ლოკალური dev-ისთვის დაემატა 2026-08-20).
      ⚠️ უფასო ngrok-დომენი გათავისუფლების შემთხვევაში სხვამ შეიძლება დაიკავოს
      და OAuth-კოდები მიიღოს — ამიტომ submit-ამდე ან ngrok-ის მიტოვებისას მოიხსნას.
      `chatassist.ge`-ის ჩანაწერს **არ შეეხო** — პროდაქშენი მას იყენებს.
- [ ] ვიდეო ხელახლა გადაიღე, თუ ვიზუალი შეიცვალა (რედიზაინის შემდეგ)
- [ ] სატესტო login (email + პაროლი) მზად არის და მუშაობს
