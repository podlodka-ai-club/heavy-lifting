import { useEffect, useState } from "react";

import { FactoryPage } from "./pages/factory/FactoryPage";
import { HomePage } from "./pages/HomePage";
import { SettingsPage } from "./pages/settings/SettingsPage";

type Route = "/" | "/factory" | "/settings";

function getRoute(pathname: string): Route {
  if (pathname === "/settings" || pathname === "/factory") {
    return pathname;
  }

  return "/";
}

export function App() {
  const [route, setRoute] = useState<Route>(() => getRoute(window.location.pathname));

  useEffect(() => {
    const onPopState = () => setRoute(getRoute(window.location.pathname));
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  function navigate(nextRoute: Route) {
    window.history.pushState({}, "", nextRoute);
    setRoute(nextRoute);
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <button className="brand-link" type="button" onClick={() => navigate("/")}>
          heavy-lifting
        </button>
        <nav aria-label="Основная навигация">
          <button
            className={route === "/factory" ? "nav-link active" : "nav-link"}
            type="button"
            onClick={() => navigate("/factory")}
          >
            Factory
          </button>
          <button
            className={route === "/settings" ? "nav-link active" : "nav-link"}
            type="button"
            onClick={() => navigate("/settings")}
          >
            Настройки
          </button>
        </nav>
      </header>
      {route === "/settings" ? <SettingsPage /> : null}
      {route === "/factory" ? <FactoryPage /> : null}
      {route === "/" ? <HomePage /> : null}
    </div>
  );
}
