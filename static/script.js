// JS file to handle the logic to change themes
document.addEventListener("DOMContentLoaded", () => {
    const themeSwitch = document.getElementById("themeSwitch");
    const themeLabel = document.getElementById("themeLabel");
    if (!themeSwitch || !themeLabel) return;

    themeSwitch.addEventListener("change", () => {
        const isDark = themeSwitch.checked;
        const theme = isDark ? "dark" : "light";

        document.documentElement.classList.toggle("dark", isDark);
        document.cookie = `theme=${theme}; path=/; max-age=31536000`;
        themeLabel.textContent = isDark ? "Dark Theme" : "Light Theme";
    });

    document.body.classList.add("transitions-enabled");
});
