import { useEffect, useState } from "react";

import { EconomicsPage } from "./pages/economics/EconomicsPage";
import { FactoryPage } from "./pages/factory/FactoryPage";
import { HomePage } from "./pages/HomePage";
import { SettingsPage } from "./pages/settings/SettingsPage";

type Route = "/" | "/factory" | "/economics" | "/settings";

function getRoute(pathname: string): Route {
  if (pathname === "/settings" || pathname === "/factory" || pathname === "/economics") {
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
            className={route === "/economics" ? "nav-link active" : "nav-link"}
            type="button"
            onClick={() => navigate("/economics")}
          >
            Money
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
      {route === "/economics" ? <EconomicsPage /> : null}
      {route === "/" ? <HomePage /> : null}
    </div>
  );
}
