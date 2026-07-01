/* პაროლის აღდგენის გვერდი — ცალკე supabase კლიენტი recovery token-ისთვის */
(function () {
  "use strict";
  var cfg = window.APP_CONFIG;

  // detectSessionInUrl:true — email-ის ბმულიდან recovery token-ის დამუშავება.
  // ცალკე კლიენტია (პანელისგან განსხ ვავებით, სადაც false-ია Facebook-ის გამო).
  var sb = supabase.createClient(cfg.SUPABASE_URL, cfg.SUPABASE_ANON_KEY, {
    auth: { detectSessionInUrl: true, persistSession: false, flowType: "implicit" },
  });

  function $(id) { return document.getElementById(id); }
  function toast(msg, isErr) {
    var t = $("toast");
    t.textContent = msg;
    t.className = "toast " + (isErr ? "toast-err" : "toast-ok");
    setTimeout(function () { t.classList.add("hidden"); }, 3500);
  }

  var ready = false;
  function showForm() {
    if (ready) return;
    ready = true;
    $("reset-loading").classList.add("hidden");
    $("reset-form").classList.remove("hidden");
    $("new-password").focus();
  }
  function showError(msg) {
    $("reset-loading").classList.add("hidden");
    $("reset-error").textContent = msg;
    $("reset-error").classList.remove("hidden");
  }

  // recovery სესია დამყარებისას გამოვაჩინოთ ფორმა
  sb.auth.onAuthStateChange(function (event, session) {
    if (event === "PASSWORD_RECOVERY" || session) showForm();
  });

  // fallback — თუ event არ ესროლა, getSession-ით შევამოწმოთ
  setTimeout(async function () {
    if (ready) return;
    try {
      var r = await sb.auth.getSession();
      if (r.data && r.data.session) showForm();
      else showError("ბმული არასწორია ან ვადაგასულია. სცადე პაროლის აღდგენა თავიდან.");
    } catch (e) {
      showError("ბმული ვერ დამუშავდა. სცადე თავიდან.");
    }
  }, 2500);

  $("reset-form").addEventListener("submit", async function (e) {
    e.preventDefault();
    var p1 = $("new-password").value;
    var p2 = $("new-password2").value;
    if (p1 !== p2) return toast("პაროლები არ ემთხ ვევა", true);
    var btn = e.target.querySelector("button[type=submit]");
    btn.disabled = true;
    try {
      var r = await sb.auth.updateUser({ password: p1 });
      if (r.error) {
        toast(r.error.message, true);
        btn.disabled = false;
        return;
      }
      $("reset-form").classList.add("hidden");
      $("reset-success").classList.remove("hidden");
    } catch (err) {
      toast(err.message || "შეცდომა", true);
      btn.disabled = false;
    }
  });
})();
