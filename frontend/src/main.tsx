import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router";

import { registerHttpObservers } from "@/app/api/http-observers";
import { AppProviders } from "@/app/providers/app-providers";
import { router } from "@/router";

import "katex/dist/katex.min.css";
import "@/styles/globals.css";

registerHttpObservers();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AppProviders>
      <RouterProvider router={router} />
    </AppProviders>
  </StrictMode>,
);
