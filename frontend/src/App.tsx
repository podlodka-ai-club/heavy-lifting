import { useEffect, useState } from "react";

import { EconomicsPage } from "./pages/economics/EconomicsPage";
import { EconomicsPage2 } from "./pages/economics/EconomicsPage2";
import { FactoryPage } from "./pages/factory/FactoryPage";
import { FactoryPage2 } from "./pages/factory/FactoryPage2";
import { HomePage } from "./pages/HomePage";
import { MicromanagementPage } from "./pages/micromanagement/MicromanagementPage";
import { RetroPage } from "./pages/retro/RetroPage";
import { SettingsPage } from "./pages/settings/SettingsPage";
import { StatsPage } from "./pages/stats/StatsPage";

type Route =
  | "/"
  | "/factory"
  | "/factory2"
  | "/economics"
  | "/economics2"
  | "/retro"
  | "/micromanagement"
  | "/stats"
  | "/settings";

function getRoute(pathname: string): Route {
  if (
    pathname === "/settings" ||
    pathname === "/factory" ||
    pathname === "/factory2" ||
    pathname === "/economics" ||
    pathname === "/economics2" ||
    pathname === "/retro" ||
    pathname === "/micromanagement" ||
    pathname === "/stats"
  ) {
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
            className={route === "/factory2" ? "nav-link active" : "nav-link"}
            type="button"
            onClick={() => navigate("/factory2")}
          >
            Factory v2
          </button>
          <button
            className={route === "/economics" ? "nav-link active" : "nav-link"}
            type="button"
            onClick={() => navigate("/economics")}
          >
            Money
          </button>
          <button
            className={route === "/economics2" ? "nav-link active" : "nav-link"}
            type="button"
            onClick={() => navigate("/economics2")}
          >
            Money v2
          </button>
          <button
            className={route === "/retro" ? "nav-link active" : "nav-link"}
            type="button"
            onClick={() => navigate("/retro")}
          >
            Retro
          </button>
          <button
            className={route === "/micromanagement" ? "nav-link active" : "nav-link"}
            type="button"
            onClick={() => navigate("/micromanagement")}
          >
            Micro
          </button>
          <button
            className={route === "/stats" ? "nav-link active" : "nav-link"}
            type="button"
            onClick={() => navigate("/stats")}
          >
            Stats
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
      {route === "/factory2" ? <FactoryPage2 /> : null}
      {route === "/economics" ? <EconomicsPage /> : null}
      {route === "/economics2" ? <EconomicsPage2 /> : null}
      {route === "/retro" ? <RetroPage /> : null}
      {route === "/micromanagement" ? <MicromanagementPage /> : null}
      {route === "/stats" ? <StatsPage /> : null}
      {route === "/" ? <HomePage /> : null}
    </div>
  );
}
