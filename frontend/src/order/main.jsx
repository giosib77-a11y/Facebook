import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import OrderPage from "./OrderPage.jsx";

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <OrderPage />
  </StrictMode>
);
