// Waiting list form. No backend yet: while data-endpoint is empty, nothing is sent or stored
// and the page says so. Set data-endpoint on the <form> to enable real submission.
(function () {
  var form = document.getElementById("waitlist");
  var box = document.getElementById("waitlist-status");
  if (!form || !box) return;
  function show(msg, isError) {
    box.hidden = false;
    box.className = "status" + (isError ? " error" : "");
    box.textContent = msg;
  }
  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var email = form.elements.email;
    if (!email.value || !email.checkValidity()) { show("Enter a valid email address.", true); email.focus(); return; }
    var url = form.getAttribute("data-endpoint");
    if (!url) { show("The waiting list is not open yet, so nothing was saved. Please check back soon.", true); return; }
    fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email: email.value, website: form.elements.website ? form.elements.website.value : "" }) })
      .then(function (r) { if (!r.ok) throw new Error(r.status); show("You're on the list. We'll email you when a spot opens.", false); form.hidden = true; })
      .catch(function () { show("Something went wrong and your address was not saved. Please try again later.", true); });
  });
})();
