// Data Deletion callback-ის status URL-ს ?code=... მოსდევს — ვაჩვენებთ დადასტურებას.
// ⚠️ რევიუ P2-16: ადრე კოდი უბრალოდ იბეჭდებოდა, ე.ი. ნებისმიერი ტექსტი
// „დადასტურებულად" ჩანდა. ახლა backend ამოწმებს ხელმოწერას.
// A-044: ადრე inline <script> იყო delete-data.html-ში; CSP script-src 'self' მას დაბლოკავდა.
(function () {
  var code = new URLSearchParams(location.search).get("code");
  if (!code) return;
  document.getElementById("confCode").textContent = code;
  document.getElementById("confirmBox").style.display = "block";

  var box = document.getElementById("confVerified");
  // გვერდი backend-ის იმავე დომენიდან იხსნება (/panel/…), ამიტომ ფარდობითი გზა მუშაობს
  // A-017: სტატუსი რეალურია (pending / completed / failed), არა ყოველთვის „დასრულებული".
  var STATES = {
    completed: ["✅ მონაცემები წაიშალა", "#059669"],
    pending: ["⏳ წაშლის მოთხოვნა მიღებულია და მუშავდება", "#b45309"],
    failed: ["⚠️ წაშლა ჯერ ვერ დასრულდა — ვამოწმებთ ხელით. საჭიროების შემთხვევაში მოგვწერეთ ქვემოთ მითითებულ მისამართზე.", "#b91c1c"],
    unknown: ["ℹ️ კოდი ნამდვილია, მაგრამ წაშლის სტატუსი ჩვენს სისტემაში არ ინახება. დასაზუსტებლად მოგვწერეთ.", "#b45309"]
  };
  fetch("/facebook/data-deletion/status?code=" + encodeURIComponent(code))
    .then(function (r) {
      if (!r.ok) throw new Error("status " + r.status);
      return r.json();
    })
    .then(function (d) {
      if (d && d.valid) {
        var when = d.requested_at ? new Date(d.requested_at).toLocaleString("ka-GE") : "";
        var st = STATES[d.status] || STATES.unknown;
        box.textContent = st[0] + (when ? " · მოთხოვნის თარიღი: " + when : "");
        box.style.color = st[1];
      } else {
        box.textContent = "⚠️ ეს კოდი ჩვენს სისტემაში ვერ მოიძებნა.";
        box.style.color = "#b45309";
      }
      box.style.display = "block";
    })
    .catch(function () {
      // ქსელი/სერვერი მიუწვდომელია — კოდი მაინც ჩანს
      box.textContent = "სტატუსის შემოწმება ახლა ვერ მოხერხდა — სცადეთ მოგვიანებით.";
      box.style.color = "#b45309";
      box.style.display = "block";
    });
})();
