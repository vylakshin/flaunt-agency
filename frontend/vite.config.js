import path from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
export default defineConfig({
    base: "/app-static/",
    plugins: [react(), tailwindcss()],
    resolve: {
        alias: {
            "@": path.resolve(__dirname, "./src"),
        },
    },
    build: {
        outDir: "dist",
        emptyOutDir: true,
    },
    server: {
        port: 5173,
        proxy: {
            "/api": "http://127.0.0.1:8000",
            "/auth": "http://127.0.0.1:8000",
            "/logout": "http://127.0.0.1:8000",
            "/dashboard": "http://127.0.0.1:8000",
            "/stats": "http://127.0.0.1:8000",
            "/settings": "http://127.0.0.1:8000",
        },
    },
});
