// Vitest-ის საერთო setup: jest-dom matcher-ები და DOM-ის გასუფთავება ყოველი ტესტის შემდეგ.
import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

afterEach(cleanup);
