/**
 * PM2 Ecosystem Configuration for slop on Raspberry Pi
 *
 * Runs both Next.js frontend and Python backend together.
 *
 * Usage:
 *   pm2 start ecosystem.config.js
 *   pm2 logs
 *   pm2 status
 */

const path = require('path')
const os = require('os')

// Detect if running on Pi or local dev
const isRaspberryPi = os.platform() === 'linux' && os.arch() === 'arm64'
const homeDir = os.homedir()

// Paths - adjust these for your setup
const SLOP_DIR = process.env.SLOP_DIR || path.join(homeDir, 'slop')
const SLOP_PI_DIR = process.env.SLOP_PI_DIR || path.join(homeDir, 'slop-pi')

module.exports = {
  apps: [
    // ===========================================
    // Next.js Frontend (port 3000)
    // ===========================================
    {
      name: 'slop-web',
      cwd: SLOP_DIR,
      script: 'npm',
      args: 'start',
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: isRaspberryPi ? '400M' : '1G',
      env: {
        NODE_ENV: 'production',
        PORT: 3000,
        // Tell frontend where Python backend is
        NEXT_PUBLIC_PYTHON_API_URL: 'http://localhost:8000',
      },
      // Logging
      error_file: path.join(SLOP_DIR, 'logs', 'web-error.log'),
      out_file: path.join(SLOP_DIR, 'logs', 'web-out.log'),
      merge_logs: true,
      log_date_format: 'YYYY-MM-DD HH:mm:ss',
      // Wait for Python to start first
      wait_ready: true,
      listen_timeout: 10000,
    },

    // ===========================================
    // Python Backend (port 8000)
    // ===========================================
    {
      name: 'slop-api',
      cwd: SLOP_PI_DIR,
      script: 'uv',
      args: 'run uvicorn app.main:app --host 0.0.0.0 --port 8000',
      interpreter: 'none',
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: isRaspberryPi ? '256M' : '512M',
      env: {
        ENVIRONMENT: 'production',
      },
      // Logging
      error_file: path.join(SLOP_PI_DIR, 'logs', 'api-error.log'),
      out_file: path.join(SLOP_PI_DIR, 'logs', 'api-out.log'),
      merge_logs: true,
      log_date_format: 'YYYY-MM-DD HH:mm:ss',
    },
  ],
}
