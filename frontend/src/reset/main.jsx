import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import ResetPage from "./ResetPage.jsx";

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <ResetPage />
  </StrictMode>
);
