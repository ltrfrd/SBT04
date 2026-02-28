import { defineConfig } from "vite";                             // Import Vite config helper
import react from "@vitejs/plugin-react";                        // Import React plugin

export default defineConfig({                                    // Export Vite configuration
  plugins: [react()],                                            // Enable React support
  server: {                                                      // Dev server settings
    proxy: {                                                     // HTTP proxy rules
      "/api": {                                                  // Anything starting with /api
        target: "http://127.0.0.1:8000",                         // Forward to FastAPI backend
        changeOrigin: true,     
        secure: false,                                 // Adjust origin header for proxy
        rewrite: (path) => path.replace(/^\/api/, ""),           // Remove /api prefix when forwarding
      },                                                         // End /api rule
    },                                                           // End proxy rules
  },                                                             // End server settings
});                                                              // End config