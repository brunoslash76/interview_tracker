import { useEffect, useState } from "react";

export function ThemeButton() {
  const [dark, setDark] = useState(
    () =>
      localStorage.getItem("theme") === "dark" ||
      (!localStorage.getItem("theme") && matchMedia("(prefers-color-scheme: dark)").matches),
  );
  useEffect(() => {
    document.documentElement.dataset.theme = dark ? "dark" : "light";
    localStorage.setItem("theme", dark ? "dark" : "light");
  }, [dark]);
  return (
    <button type="button" className="pill-button" onClick={() => setDark(!dark)}>
      {dark ? "Light" : "Dark"}
    </button>
  );
}
