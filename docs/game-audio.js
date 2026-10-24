// Audio pool from the 0.16.0 Electron renderer, using bundled same-origin media.
const AUDIO_POOL_SIZE = 60;
const DEFAULT_VOLUME = 0.9;

export class AudioEngine {
    constructor(manifest, audioRoot) {
        this.audioRoot = audioRoot;
        this.manifest = manifest;
        this.pool = [];
        this.nextId = 1;
        this.byId = new Map();
        // 这些 clip 只允许一份在播。Pinata 的循环曲会被 bundle 里
        // 两条路径重复启动（原版 bug），在这里兜底，避免叠音。
        // 只列循环曲，普通音效不去重 —— 它们本来就要多实例。
        this.dedupeNames = new Set([
            'Music_Pinata_PartyLoop',
        ]);
        // 去重名单里每个名字绑定一个固定 slot，永不参与池分配，
        // 也不被 cleanupFinished 回收。一对一 ⇒ 不可能出现第二个元素。
        this.dedicated = new Map();
    }

    async init() {
        for (let i = 0; i < AUDIO_POOL_SIZE; i++) {
            const el = new Audio();
            el.preload = 'auto';
            el.preservesPitch = false;
            this.pool.push({
                el: el,
                id: null,
                name: null,
                playing: false,
                fading: false,
                speed: 1,
                volume: DEFAULT_VOLUME,
                restartBeforeEnd: null,
                restartTimer: null,
                fadeTimer: null,
            });
        }
    }

    nameToPath(name) {
        return this.manifest[name] ?? null;
    }

    getFreeSlot(name) {
        const free = this.pool.find(s => !s.playing && !s.dedicated);
        if (free) return free;

        // 池满了。以前这里直接返回 null，调用方就丢弃音效 ——
        // 一旦池被占满，玩家听到的就是「音效变少了」。
        // 改成抢一个最接近播完的一次性音效 slot。
        // 绝不能抢 dedupeNames 里的循环曲，否则会把背景循环掐断。
        let victim = null;
        for (const s of this.pool) {
            if (!s.playing) continue;
            if (s.dedicated) continue;
            if (!victim || s.el.currentTime > victim.el.currentTime) victim = s;
        }
        if (victim) {
            this.releaseSlot(victim);
            return victim;
        }
        console.warn('[audio] pool exhausted, drop:', name);
        return null;
    }

    // 停止指定名字的所有实例，返回停掉的个数。
    stopByName(name) {
        let n = 0;
        for (const slot of this.pool) {
            if (slot.playing && slot.name === name) {
                this.releaseSlot(slot);
                n++;
            }
        }
        return n;
    }

    // 取（必要时创建）某名字的专属 slot。只建一次，之后永远复用。
    _dedicatedSlot(name) {
        let slot = this.dedicated.get(name);
        if (slot) return slot;

        const el = new Audio();
        el.preload = 'auto';
        el.preservesPitch = false;
        slot = {
            el: el,
            id: null,
            name: null,
            playing: false,
            fading: false,
            speed: 1,
            volume: DEFAULT_VOLUME,
            restartBeforeEnd: null,
            restartTimer: null,
            fadeTimer: null,
            dedicated: name,
        };
        this.dedicated.set(name, slot);
        return slot;
    }

    play(name, speed = 1, volume = DEFAULT_VOLUME) {
        let slot;
        if (this.dedupeNames.has(name)) {
            slot = this._dedicatedSlot(name);
            // 专属 slot 已在播：只更新参数，绝不开第二个。
            if (slot.playing && !slot.el.paused) {
                slot.volume = Math.min(1, Math.max(0, volume));
                slot.el.volume = slot.volume;
                slot.el.playbackRate = speed;
                slot.speed = speed;
                return slot.id;
            }
        } else {
            slot = this.getFreeSlot(name);
            if (!slot) {
                console.warn('[audio] pool exhausted, drop:', name);
                return null;
            }
        }

        const relPath = this.nameToPath(name);
        if (!relPath) {
            console.warn('[audio] unknown clip:', name);
            return null;
        }
        const src = new URL(relPath.split('/').map(encodeURIComponent).join('/'), this.audioRoot).href;

        const el = slot.el;
        if (slot.restartTimer) { clearTimeout(slot.restartTimer); slot.restartTimer = null; }
        if (slot.fadeTimer) { clearInterval(slot.fadeTimer); slot.fadeTimer = null; }

        el.pause();
        el.src = src;
        el.playbackRate = speed;
        el.preservesPitch = false;
        el.volume = Math.min(1, Math.max(0, volume));

        slot.id = this.nextId++;
        slot.name = name;
        slot.playing = true;
        slot.fading = false;
        slot.speed = speed;
        slot.volume = volume;
        slot.restartBeforeEnd = null;

        this.byId.set(slot.id, slot);

        el.onended = () => this.releaseSlot(slot);
        el.onerror = () => {
            console.error('[audio] load error:', src);
            this.releaseSlot(slot);
        };

        el.play().catch(err => {
            console.error('[audio] play failed:', err);
            this.releaseSlot(slot);
        });

        return slot.id;
    }

    releaseSlot(slot) {
        if (!slot.playing) return;
        slot.playing = false;
        slot.name = null;
        slot.fading = false;
        slot.restartBeforeEnd = null;

        if (slot.restartTimer) {
            clearTimeout(slot.restartTimer);
            slot.restartTimer = null;
        }
        if (slot.fadeTimer) {
            clearInterval(slot.fadeTimer);
            slot.fadeTimer = null;
        }

        const el = slot.el;
        el.onended = null;
        el.onerror = null;
        el.pause();
        el.removeAttribute('src');
        el.load();

        if (slot.id !== null) this.byId.delete(slot.id);
        slot.id = null;
    }

    getSlot(id) {
        return this.byId.get(id) || null;
    }

    setVolume(id, volume) {
        const slot = this.getSlot(id);
        if (!slot) return;
        slot.volume = Math.min(1, Math.max(0, volume));
        slot.el.volume = slot.volume;
    }

    setPlaying(id, playing) {
        const slot = this.getSlot(id);
        if (!slot) return;
        if (playing) {
            slot.el.play().catch(() => { });
        } else {
            slot.el.pause();
        }
    }

    seek(id, seconds) {
        const slot = this.getSlot(id);
        if (!slot) return;
        const el = slot.el;
        const target = Math.max(0, seconds);

        const apply = () => {
            if (el.seekable.length > 0) {
                el.currentTime = Math.min(target, el.duration || target);
            } else {
                console.warn('[audio] seekable still empty');
            }
        };

        if (el.readyState >= 1 && el.seekable.length > 0) {
            apply();
        } else {
            el.addEventListener('loadedmetadata', apply, { once: true });
        }
    }

    getPosition(id) {
        const slot = this.getSlot(id);
        if (!slot) return [0, null];
        const el = slot.el;
        const total = isFinite(el.duration) ? el.duration : null;
        return [el.currentTime, total];
    }

    getDuration(id) {
        const slot = this.getSlot(id);
        if (!slot) return null;
        return isFinite(slot.el.duration) ? slot.el.duration : null;
    }

    fadeOut(id, durationMs) {
        const slot = this.getSlot(id);
        if (!slot || slot.fading) return;
        slot.fading = true;

        const startVol = slot.el.volume;
        const steps = 30;
        const stepMs = durationMs / steps;
        let i = 0;

        slot.fadeTimer = setInterval(() => {
            i++;
            const v = startVol * (1 - i / steps);
            slot.el.volume = Math.max(0, v);
            if (i >= steps) {
                clearInterval(slot.fadeTimer);
                slot.fadeTimer = null;
                this.destroy(id);
            }
        }, stepMs);
    }

    setRestartBeforeEnd(id, beforeMs) {
        const slot = this.getSlot(id);
        if (!slot) return;
        slot.restartBeforeEnd = beforeMs / 1000;

        const schedule = () => {
            if (!slot.playing || slot.restartBeforeEnd === null) return;
            const el = slot.el;
            if (!isFinite(el.duration)) {
                slot.restartTimer = setTimeout(schedule, 100);
                return;
            }
            const target = el.duration - slot.restartBeforeEnd / slot.speed;
            const remaining = (target - el.currentTime) * 1000 / slot.speed;
            if (remaining <= 0) {
                el.currentTime = 0;
                schedule();
            } else {
                slot.restartTimer = setTimeout(() => {
                    if (!slot.playing) return;
                    el.currentTime = 0;
                    schedule();
                }, remaining);
            }
        };
        schedule();
    }

    destroy(id) {
        const slot = this.getSlot(id);
        if (!slot) return;
        this.releaseSlot(slot);
    }

    cleanupFinished() {
        let count = 0;
        for (const slot of this.pool) {
            if (slot.dedicated) continue;
            if (!slot.playing && slot.el.src) {
                slot.el.removeAttribute('src');
                slot.el.load();
                if (slot.id !== null) this.byId.delete(slot.id);
                slot.id = null;
                count++;
            }
        }
        return count;
    }

    listClips() {
        return Object.keys(this.manifest);
    }
}

export async function initializeGameAudio() {
    const audioRoot = new URL('audio/', document.baseURI);
    const response = await fetch(new URL('manifest.json', audioRoot));
    if (!response.ok) throw new Error(`Audio manifest HTTP ${response.status}`);
    const engine = new AudioEngine(await response.json(), audioRoot);
    await engine.init();
    window.audioEngine = engine;
}
