import axios from 'axios';

// Create an axios instance with default config
export const client = axios.create({
  // Prefer relative `/api` so it works for both:
  // - Vite dev server with proxy
  // - Backend-served production build
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api',
  headers: {
    'Content-Type': 'application/json',
  },
});

// Add response interceptor for error handling
client.interceptors.response.use(
    (response) => response,
    (error) => {
        // Handle global errors here if needed
        console.error('API Error:', error);
        return Promise.reject(error);
    }
);
