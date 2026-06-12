document.addEventListener("DOMContentLoaded", () => {
  const alerts = document.querySelectorAll(".flash");
  alerts.forEach((alert) => {
    setTimeout(() => {
      alert.style.opacity = "0";
      alert.style.transition = "opacity 300ms ease";
    }, 3500);
  });
});
