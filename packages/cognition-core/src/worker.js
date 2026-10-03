import { spawn } from 'node:child_process';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';

/** One private process connection. Model token streams never cross this boundary. */
export class BusinessWorker {
  constructor(config, onEvent, logger) {
    this.pending = new Map();
    this.serial = 0;
    this.closed = false;
    this.process = spawn(config.python, ['-u', '-m', 'asuna.native_worker', '--config', config.configPath], {
      cwd: config.workspace, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'],
      env: { ...process.env, PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8', PYTHONDONTWRITEBYTECODE: '1',
        ASUNA_DATA_ROOT: config.workspace,
        PYTHONPATH: config.pythonPath ?? fileURLToPath(new URL('../python', import.meta.url)) },
    });
    this.lines = createInterface({ input: this.process.stdout });
    this.lines.on('line', line => {
      try {
        const message = JSON.parse(line);
        if (message.id !== undefined) {
          const pending = this.pending.get(message.id);
          if (!pending) return;
          this.pending.delete(message.id);
          if (message.error) pending.reject(new Error(message.error));
          else pending.resolve(message.value);
        } else Promise.resolve(onEvent(message)).catch(error => logger.warn(String(error)));
      } catch (error) { this.fail(error); }
    });
    this.process.stderr.on('data', chunk => logger.warn(chunk.toString()));
    this.process.on('error', error => this.fail(error));
    this.process.on('exit', code => this.fail(new Error(`Asuna business worker exited (${code})`)));
  }

  fail(error) {
    this.closed = true;
    for (const pending of this.pending.values()) pending.reject(error);
    this.pending.clear();
    this.onFailure?.(error);
  }

  call(method, args = {}) {
    if (this.closed) return Promise.reject(new Error('Asuna business worker is unavailable'));
    const id = ++this.serial;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.process.stdin.write(JSON.stringify({ id, method, args }) + '\n', error => {
        if (error) { this.pending.delete(id); reject(error); }
      });
    });
  }

  async dispose() {
    this.process.stdin.end();
    if (this.process.exitCode !== null) return;
    await new Promise(resolve => {
      const timer = setTimeout(() => { this.process.kill(); resolve(); }, 5000);
      this.process.once('exit', () => { clearTimeout(timer); resolve(); });
    });
    this.lines.close();
  }
}
