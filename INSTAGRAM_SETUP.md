# 📸 Instagram-ის ჩართვა — გაკეთების ინსტრუქცია

> კოდი მზადაა (webhook `object=="instagram"`-ს ამუშავებს, connect IG account id-ს ინახავს,
> migration 0006 გაშვებულია). დარჩა მხოლოდ **Meta-ს მხარის კონფიგი** — ეს ფაილი ამას აღწერს.
> გადადებულია — როცა IG Business ანგარიშზე წვდომა გექნება, ამ ნაბიჯებით დაასრულებ.

---

## ვის რა სჭირდება

| ვინ | სჭირდება IG ანგარიში? |
|---|---|
| შენ — Meta App-ის კონფიგი | ❌ არა |
| შენ — ტესტი / App Review | ✅ ერთი (თუნდაც სატესტო/სხვისი) |
| გამყიდველი | ✅ თავისი (თუ აქვს — მაშინვე მუშაობს) |

**მთავარი:** app-level კონფიგს შენი პირადი IG არ სჭირდება. მაგრამ App Review-ს
Meta screencast-ს ითხოვს → ერთი ცოცხალი IG Business ანგარიში დაგჭირდება საჩვენებლად
(შეიძლება სატესტო/დროებითი).

---

## ეტაპი 1: Instagram Business ანგარიში (გამყიდვლის მხარე)
1. Instagram აპში → ანგარიშის შექმნა (თუ არ აქვს)
2. Settings and privacy → Account type and tools → Switch to professional → **Business**
3. ⚠️ Settings → Messages and story replies → **Connected tools / Allow access to messages → ჩართე**
   (ამის გარეშე გარე აპი ვერ წაიკითხავს DM-ებს)

## ეტაპი 2: Facebook გვერდთან მიბმა
4. Facebook გვერდი → Settings → Linked accounts → Instagram → **Connect account**
   (ან Meta Business Suite → Settings → Accounts → Instagram → Connect)
5. IG იმავე გვერდზე უნდა იყოს მიბმული, რომელსაც ბოტში აკავშირებ

## ეტაპი 3: Meta App Dashboard (developers.facebook.com)
6. App → **Add Product** → **Instagram** → Set up
7. **Webhooks** → object drop-down → **Instagram** → Subscribe ველზე **`messages`**
   - Callback URL: იგივე (`.../webhook`), Verify Token: იგივე რაც Messenger-ს
8. **ნებართვები:** `instagram_basic` + `instagram_manage_messages`
   - dev mode — admin/tester მუშაობს
   - საჯაროდ — **App Review** (screencast-ით)

## ეტაპი 4: გვერდის ხელახლა დაკავშირება
9. ბოტის პანელი → Facebook გვერდი → **გათიშვა → თავიდან დაკავშირება**
   (ახალი IG-ნებართვები + IG account id რომ ჩაიწეროს)

---

## როგორ გავიგებ რომ იმუშავა
- პანელში FB სექციაში ჩანს **„+ 📸 Instagram"**
- Instagram DM-ში მისწერ მაღაზიას → ბოტი უპასუხებს (იგივე ლოგიკით, იგივე მარაგით)

---

## ⚠️ Development mode
App Review-მდე მხოლოდ app-ის admin/tester ურთიერთობს ბოტთან. ტესტისთვის ის IG
ანგარიში app-ის tester-ად უნდა დაამატო.
