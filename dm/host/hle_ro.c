// nn::ro dynamic modules (NRO): on a real device the game reads the .nro into memory and hands it to
// nn::ro::LoadModule, and the system maps it as executable code. Apple platforms do not allow
// executing code written at run time, so dynamic modules are rewritten offline like main / sdk,
// loaded with the host and relocated across modules (just give more module names on the command
// line); here the nn::ro interface is taken over as "recognize the already-loaded copy by build
// ID", and its global constructors run only at this point.
// Thread-local variables (R_AARCH64_TLSDESC): one zeroed block per thread per module; the resolver
// returns "variable address − thread pointer".
// Known limitation: the non-zero initial-value template of .tdata is not fetched (an NRO has no
// program headers; the template location is yet to be located), so a thread_local with a non-zero
// constant initializer reads 0.
// Adapted from Jhaizhou-ops/nx-port (MIT), which proved the design on a second title.
#include "hle.h"

#define RO_TLS_SIZE 0x10000
static pthread_key_t g_rotls[MAX_MOD];
static pthread_once_t g_rotls_once = PTHREAD_ONCE_INIT;
static void rotls_keys(void) { for (int i = 0; i < MAX_MOD; i++) if (pthread_key_create(&g_rotls[i], free)) die("nn::ro: cannot create the thread-local storage keys"); }

// Second word of the descriptor: top 8 bits module index, low 56 bits the variable's offset inside
// that module's thread-local segment
uint64_t ro_tlsdesc_c(const uint64_t *desc) {
    unsigned mi = (unsigned)(desc[1] >> 56); uint64_t off = desc[1] & 0x00ffffffffffffffull;
    uint8_t *blk = pthread_getspecific(g_rotls[mi]);
    if (!blk) { blk = calloc(1, RO_TLS_SIZE); if (!blk) die("nn::ro: thread-local storage allocation failed"); pthread_setspecific(g_rotls[mi], blk); }
    return (uint64_t)(blk + off) - (uint64_t)pthread_getspecific(g_keytls);
}
// TLSDESC calling convention: x0 = descriptor address, result in x0; every register other than
// x0, x1, x30 (floating point included) must be preserved, so everything is saved here before entering C
__attribute__((naked)) static void ro_tlsdesc_entry(void) {
    __asm__ volatile(
        "sub sp, sp, #0x2c0\n"
        "stp x2, x3, [sp, #0x00]\n stp x4, x5, [sp, #0x10]\n stp x6, x7, [sp, #0x20]\n stp x8, x9, [sp, #0x30]\n"
        "stp x10, x11, [sp, #0x40]\n stp x12, x13, [sp, #0x50]\n stp x14, x15, [sp, #0x60]\n stp x16, x17, [sp, #0x70]\n"
        "stp x29, x30, [sp, #0x80]\n str x1, [sp, #0x90]\n"
        "stp q0, q1, [sp, #0xa0]\n stp q2, q3, [sp, #0xc0]\n stp q4, q5, [sp, #0xe0]\n stp q6, q7, [sp, #0x100]\n"
        "stp q16, q17, [sp, #0x120]\n stp q18, q19, [sp, #0x140]\n stp q20, q21, [sp, #0x160]\n stp q22, q23, [sp, #0x180]\n"
        "stp q24, q25, [sp, #0x1a0]\n stp q26, q27, [sp, #0x1c0]\n stp q28, q29, [sp, #0x1e0]\n stp q30, q31, [sp, #0x200]\n"
        "bl _ro_tlsdesc_c\n"
        "ldp q30, q31, [sp, #0x200]\n ldp q28, q29, [sp, #0x1e0]\n ldp q26, q27, [sp, #0x1c0]\n ldp q24, q25, [sp, #0x1a0]\n"
        "ldp q22, q23, [sp, #0x180]\n ldp q20, q21, [sp, #0x160]\n ldp q18, q19, [sp, #0x140]\n ldp q16, q17, [sp, #0x120]\n"
        "ldp q6, q7, [sp, #0x100]\n ldp q4, q5, [sp, #0xe0]\n ldp q2, q3, [sp, #0xc0]\n ldp q0, q1, [sp, #0xa0]\n"
        "ldr x1, [sp, #0x90]\n ldp x29, x30, [sp, #0x80]\n"
        "ldp x16, x17, [sp, #0x70]\n ldp x14, x15, [sp, #0x60]\n ldp x12, x13, [sp, #0x50]\n ldp x10, x11, [sp, #0x40]\n"
        "ldp x8, x9, [sp, #0x30]\n ldp x6, x7, [sp, #0x20]\n ldp x4, x5, [sp, #0x10]\n ldp x2, x3, [sp, #0x00]\n"
        "add sp, sp, #0x2c0\n ret\n");
}
void ro_tlsdesc_fill(module_t *m, uint64_t *where, uint64_t off) {
    pthread_once(&g_rotls_once, rotls_keys);
    if (off >= RO_TLS_SIZE) die("%s: thread-local variable offset %#llx exceeds the reserved %#x", m->name, (unsigned long long)off, RO_TLS_SIZE);
    where[0] = (uint64_t)ro_tlsdesc_entry; where[1] = (uint64_t)(m - g_mod) << 56 | off;
}

// nn::ro::Module: only the first two words are used (loaded-module pointer, state 1 = loaded); every interface that reads it is taken over in this file
typedef struct { module_t *mod; uint32_t state; } ro_module;
static module_t *ro_find(const uint8_t *image) {
    if (!image || memcmp(image + 0x10, "NRO0", 4)) return NULL;
    for (int i = 0; i < g_nmod; i++) if (g_mod[i].late && !memcmp(g_mod[i].base + 0x40, image + 0x40, 0x20)) return &g_mod[i];
    return NULL;
}
HLE_FORCE("_ZN2nn2ro10InitializeEv", "dynamic modules are preloaded by the host, no ldr:ro service", void, h_ro_Initialize, void) { LOG("nn::ro::Initialize"); }
HLE_FORCE("_ZN2nn2ro8FinalizeEv", "dynamic modules are preloaded by the host", void, h_ro_Finalize, void) {}
HLE_FORCE("_ZN2nn2ro18RegisterModuleInfoEPNS0_16RegistrationInfoEPKv", "signature registration (NRR): the host does not verify", Result, h_ro_RegisterModuleInfo, void *info, const void *nrr) { (void)info; (void)nrr; LOG("nn::ro::RegisterModuleInfo"); return RES_OK; }
HLE_FORCE("_ZN2nn2ro18RegisterModuleInfoEPNS0_16RegistrationInfoEPKvj", "signature registration (NRR): the host does not verify", Result, h_ro_RegisterModuleInfo2, void *info, const void *nrr, uint32_t n) { (void)info; (void)nrr; (void)n; return RES_OK; }
HLE_FORCE("_ZN2nn2ro20UnregisterModuleInfoEPNS0_16RegistrationInfoE", "signature registration (NRR): the host does not verify", void, h_ro_UnregisterModuleInfo, void *info) { (void)info; }
HLE_FORCE("_ZN2nn2ro13GetBufferSizeEPmPKv", "bss size from the NRO header; the actual bss is already in the preloaded image", Result, h_ro_GetBufferSize, uint64_t *out, const uint8_t *image) {
    uint32_t bss = 0; if (image && !memcmp(image + 0x10, "NRO0", 4)) memcpy(&bss, image + 0x38, 4);
    *out = ((uint64_t)bss + 0xfff) & ~0xfffull; return RES_OK;
}
HLE_FORCE("_ZN2nn2ro10LoadModuleEPNS0_6ModuleEPKvPvmi", "recognize the host-preloaded copy by build ID, and run its global constructors at this point", Result, h_ro_LoadModule, ro_module *out, const uint8_t *image, void *bss, uint64_t bss_size, int flag) {
    (void)bss; (void)bss_size;
    module_t *m = ro_find(image);
    if (!m) { LOG("[RED] nn::ro::LoadModule: the dynamic module the game wants is not preloaded (rewrite it offline and add its name to the host's module list)"); return RES_FAIL; }
    LOG("nn::ro::LoadModule → %s (base %p, flag %d)", m->name, m->base, flag);
    out->mod = m; out->state = 1;
    static uint8_t inited[MAX_MOD];
    if (!inited[m - g_mod]) { inited[m - g_mod] = 1; run_module_init_one(m); }
    LOG("nn::ro::LoadModule ← %s global constructors done", m->name);
    return RES_OK;
}
HLE_FORCE("_ZN2nn2ro12UnloadModuleEPNS0_6ModuleE", "preloaded modules are not unloaded", void, h_ro_UnloadModule, ro_module *mod) { if (mod) mod->state = 0; }
HLE_FORCE("_ZN2nn2ro12LookupSymbolEPmPKc", "search all loaded modules by name", Result, h_ro_LookupSymbol, uint64_t *out, const char *name) {
    void *p = guest_sym(name); if (!p) { LOG("nn::ro::LookupSymbol cannot find %s", name); return RES_FAIL; }
    *out = (uint64_t)p; return RES_OK;
}
HLE_FORCE("_ZN2nn2ro18LookupModuleSymbolEPmPKNS0_6ModuleEPKc", "search the named preloaded module", Result, h_ro_LookupModuleSymbol, uint64_t *out, const ro_module *mod, const char *name) {
    void *p = mod && mod->mod ? module_sym(mod->mod, name) : NULL; if (!p) { LOG("nn::ro::LookupModuleSymbol cannot find %s", name); return RES_FAIL; }
    *out = (uint64_t)p; return RES_OK;
}
HLE_FORCE("_ZN2nn2ro12ProtectRelroEPKvS2_S2_S2_S2_", "read-only relocation protection: the host does not change page permissions", void, h_ro_ProtectRelro, const void *a, const void *b, const void *c, const void *d, const void *e) { (void)a; (void)b; (void)c; (void)d; (void)e; }
HLE_FORCE("_ZN2nn2ro29ProtectFullRelroForAllModulesEv", "read-only relocation protection: the host does not change page permissions", void, h_ro_ProtectFullRelro, void) {}
