document.addEventListener("DOMContentLoaded", function () {
  const nameInput = document.getElementById("name");
  if (!nameInput) return;
  const nameError = document.getElementById("nameError");
  const submitBtn = document.querySelector("button[type='submit']") || document.querySelector("button");

  function validateName() {
    const value = nameInput.value.trim();
    if (value.length === 0) {
      nameInput.classList.add("input-error");
      if (nameError) nameError.style.display = "block";
      if (submitBtn) submitBtn.disabled = true;
    } else {
      nameInput.classList.remove("input-error");
      if (nameError) nameError.style.display = "none";
      if (submitBtn) submitBtn.disabled = false;
    }
  }

  nameInput.addEventListener("input", validateName);
  validateName();
});
