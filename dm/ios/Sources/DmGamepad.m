// Virtual gamepad (Nintendo button positions) + physical controllers (GameController). Both are merged and handed to the host through dm_input_set (hle_hid.c, bit layout in dm_input.h).
//   Three layouts; one tap on the layout button at the top centre (labelled with the current layout, "2D" / "3D" / "H2") cycles them, and the choice is kept in NSUserDefaults (each game is its own app, so per game); the first launch uses the game profile's pad_layout (DM_GAME_PAD_FULL).
//   2D (simple): top corners ZL above L (one column), ZR above R likewise, teardrops with the tip toward the screen corner; − and + side by side at the top centre; the left stick in the bottom-left corner (fixed ring, tilt measured from the ring centre, small dead zone);
//     the A (right) B (bottom) X (top) Y (left) diamond in the bottom-right corner, sliding a finger between keys switches keys. Each bottom corner holds a single control, so it sits close in (reaching halfway into the side safe-area inset).
//   3D (full, Pro Controller style): everything in 2D (left stick and diamond keep their place and size), plus a D-pad (inward of and below the left stick, 8-way), a right stick (inward of and below the diamond, a smaller ring)
//     and L3 / R3 (small round keys in the top row, inward of ZL / ZR). Breath of the Wild crouches with L3 and uses the scope with R3; 3D World and Breath of the Wild turn the camera with the right stick.
//   H2 (Hades II, see the block below): a floating stick on the left (the base starts wherever the
//     finger lands) and combat keys on the right, sized by the game's own use frequency, with the
//     Ω latch standing in for the pad's hold-ZR modifier.
//   Touch-down ownership: locked keys first (shoulders, − / +, the layout button, L3 / R3), then whichever of the diamond, the D-pad and the two sticks has the smallest distance / grab radius (the left stick's grab circle borders the D-pad).
//   Everything hugs the edges and corners to leave the picture room; controls sit over the picture, one CAShapeLayer each: a press only swaps the fill, a stick only moves its knob, nothing redraws the whole screen.
//   Touches no control takes go to the game's touch screen (pushGame; Super Mario Galaxy's pointer in handheld mode).
//   The virtual gamepad (layout button included) hides while a physical controller is connected and comes back when it is removed; meanwhile every touch goes to the game. Physical controllers keep every button (D-pad and right stick included) and map by position: bottom = B, right = A, left = Y, top = X (same positions as on a Switch controller).
//   ---- Hades II layout ----
//   The stick starts wherever the finger lands inside the lower-left start zone (40% of the width,
//   from 45% of the height down): the base centre = the touch point, direction and magnitude are
//   measured from that point, and dragging any distance keeps working (the base does not follow the
//   finger). A touch outside the zone that hits nothing else goes to the game's touch screen, as in
//   the other layouts. A stick finger cancelled by the system (notification banner, system gesture)
//   resumes when a finger lands near the same place within 2 s, keeping the old base centre so the
//   base does not jump.
//   The right side holds the combat keys, laid out by the game's own frequency (from the help text:
//   Attack 32 hints, Special 25, Dash 17, Cast 8, Hex 9) and the Switch mapping (Y attack, X special,
//   B dash, A cast):
//     Y attack   biggest, rightmost (thumb rest) — holding passes the press duration through, which is the Ω attack
//     X special  second size, upper-left of Y    — the Ω special works the same way
//     B dash     third size, below, wide hit area (the most救命 key)
//     A cast     smaller, inner
//     ZR omega   the Ω moves are "hold ZR then press attack / special" on a pad; here the key is a
//                latch: tap once to arm (the ring lights), the next attack / special press carries
//                ZR 0.12 s ahead of itself (the game's own "hold ZR first" order), then it disarms.
//                Holding the key works as well.
//     R hex      smallest, innermost: the blue-meter spell (hold-and-release variants pass through)
//   Each combat key draws the game's own glyph when the profile ships one
//   (dm/games/<id>/pad_icons/<name>.png); without one it falls back to the button letter.
#import <UIKit/UIKit.h>
#import <GameController/GameController.h>
#import <CoreText/CoreText.h>
#include <pthread.h>
#include "dm_input.h"
#include "front.h"
#include "game_profile.h"

enum { B_A = 0, B_B, B_X, B_Y, B_LS, B_RS, B_L, B_R, B_ZL, B_ZR, B_PLUS, B_MINUS, B_LEFT, B_UP, B_RIGHT, B_DOWN, B_N };
enum { C_NONE = 0, C_STICK, C_DPAD, C_FACE, C_BTN, C_SWAP, C_GAME, C_H2KEY };   // C_GAME: none, the touch goes to the game's touch screen (finger slot << 8); C_H2KEY: a Hades II combat key (key << 8)

// ---- Hades II layout constants ----
// Key radii: attack biggest, hex smallest (sized by use frequency, see the header comment).
static const CGFloat KH_Y_R = 40, KH_X_R = 33, KH_B_R = 34, KH_A_R = 26, KH_ZR_R = 25, KH_R_R = 20;
// H2 key centres from Y (the anchor), in u. The whole cluster hugs the thumb's rest arc: Y under
// the thumb, X up-left, B left-down, A inward-down, ZR directly above Y, R inward below A. The R
// key is the game's universal interact (door / IOR return / cast field detonate), so it sits in
// the frequent band, not in a corner. Y itself: KH_FACE_X from the right edge, KH_FACE_Y up.
static const CGFloat KH_FACE_X = 118, KH_FACE_Y = 88,
    KH_X_DX = -66, KH_X_DY = -44,
    KH_B_DX = -88, KH_B_DY = 26,
    KH_A_DX = 40, KH_A_DY = 88,
    KH_ZR_DX = -4, KH_ZR_DY = -108,
    KH_R_DX = 34, KH_R_DY = 148;
// The menu pad: a handle on the left edge mid-height expands a small D-pad (menu navigation) with
// the two bumpers beside it — the keys menus want (D-pad right opens the inventory, L / R page
// through it) while costing nothing in combat. It hides again 4 s after the last touch on it.
static const CGFloat KH_MENU_HANDLE_X = 6, KH_MENU_HANDLE_Y = 0.42, KH_MENU_HANDLE_R = 22,
    KH_MENU_X = 64, KH_MENU_Y = 0.40,       // the D-pad centre: from the left edge, fraction of the height
    KH_MENU_R = 40, KH_MENU_ARM = 17, KH_MENU_IN = 12,
    KH_MENU_L_DX = 116, KH_MENU_L_DY = -62,  // L: inward and above the D-pad
    KH_MENU_R_DX = 116, KH_MENU_R_DY = 62,   // R: inward and below
    KH_MENU_HIDE_S = 4.0;
// Floating stick: the start zone's right bound (fraction of the width) and upper bound (fraction of
// the height from the bottom); the base radius, full-tilt fraction, dead zone, the resume window for
// a system-cancelled stick finger, its grab factor, and how long the Ω latch leads the attack key.
static const CGFloat KH_ZONE_R = 0.40, KH_ZONE_T = 0.45, KH_STICK_R = 62, KH_FULL = 0.75,
    KH_DEAD = 0.08, KH_RESUME_S = 2.0, KH_RESUME_K = 1.6, KH_ZR_LEAD = 0.12;

static pthread_mutex_t g_mu = PTHREAD_MUTEX_INITIALIZER;
static uint64_t g_touch_btn, g_pad_btn;
static int32_t g_touch_lx, g_touch_ly, g_touch_rx, g_touch_ry, g_pad_lx, g_pad_ly, g_pad_rx, g_pad_ry;
static int tilted(int32_t x, int32_t y) { return (int64_t)x * x + (int64_t)y * y > (int64_t)4000 * 4000; }
static void publish(void) {
    pthread_mutex_lock(&g_mu);
    int32_t lx = g_touch_lx, ly = g_touch_ly, rx = g_touch_rx, ry = g_touch_ry;
    if (tilted(g_pad_lx, g_pad_ly)) { lx = g_pad_lx; ly = g_pad_ly; }   // a tilted physical stick wins
    if (tilted(g_pad_rx, g_pad_ry)) { rx = g_pad_rx; ry = g_pad_ry; }
    dm_input_set(g_touch_btn | g_pad_btn, lx, ly, rx, ry);
    pthread_mutex_unlock(&g_mu);
}

// ---- Layout constants (in u; x measured from the outer edge, the right half mirrors) ----
static const CGFloat
    K_ZL_X = 44, K_ZL_Y = 40, K_ZL_R = 26,          // ZL / ZR: centre from the outer edge and the top, radius
    K_L_X = 44, K_L_Y = 108, K_L_R = 24,            // L / R: same column as ZL / ZR
    K_DROP_TIP = 1.45,                              // teardrop tip distance from the centre (times the radius)
    K_CORNER_IN = 0.5,                              // how far the bottom-corner controls reach into the side safe-area inset (in landscape there is only the rounded screen corner there; the Dynamic Island is mid-edge)
    K_FACE_X = 81, K_PAD_Y = 82,                    // diamond centre from the outer edge; diamond and stick centre from the bottom (B's lower edge about 5 above it)
    K_FACE_GAP = 50, K_FACE_R = 27,                 // diamond: key distance from the centre, key radius
    K_PILL_DX = 52, K_PILL_Y = 22, K_PILL_W = 50, K_PILL_H = 28,   // − / +: centre from the screen's midline (the middle goes to the layout button) and from the top, size
    K_SWAP_R = 15,                                  // layout button: top centre, level with − / +
    K_STICK_X = 81, K_STICK_R = 77, K_KNOB_R = 30,  // left stick: mirrors the diamond, the ring as large as the whole diamond (key distance + key radius), the knob a little larger than a diamond key
    K_STICK_GRAB = 1.4,                             // how near the ring centre a touch-down grabs a stick (times the ring radius)
    K_FULL = 0.8,                                   // full tilt at this fraction of the ring radius (the knob still travels to the ring edge)
    K_DEAD = 0.1,                                   // stick dead zone (times the ring radius)
    // controls only the 3D layout has
    K_LOW_X = 231, K_LOW_Y = 64,                    // D-pad / right stick centre from the outer edge and the bottom (inward of and below the left stick / the diamond, as on a Pro Controller)
    K_DPAD_R = 48, K_ARM_W = 17, K_ARM_IN = 11,     // D-pad: arm outer edge from the centre, half-width, tip from the centre
    K_DPAD_GRAB = 1.3,                              // D-pad grab radius (times the outer edge)
    K_RSTICK_R = 60, K_RKNOB_R = 24,                // right stick: ring and knob radius
    K_CLICK_X = 102, K_CLICK_R = 17;                // L3 / R3: centre from the outer edge (level with ZL / ZR), radius
static const int k_btns[] = {B_ZL, B_L, B_ZR, B_R, B_MINUS, B_PLUS, B_LS, B_RS};   // keys locked at touch-down (L3 / R3 only in the 3D layout)
static NSString *const k_layout_key = @"DmPadLayout";   // NSUserDefaults: 1 = 3D, 0 = 2D
static NSString *const k_h2_key = @"DmPadH2";           // NSUserDefaults: 1 = Hades II layout (overrides 2D / 3D)

// ---- Hades II combat keys ----
// Each entry: button, centre from Y (the anchor) in u, radius in u, icon name. Y sits at the thumb's
// rest point; the rest fan out by use frequency (attack biggest and under the thumb, hex smallest).
typedef struct { int b; CGFloat dx, dy, r; NSString *icon; } h2key;
static const h2key k_h2[] = {
    { B_Y,  0,      0,    KH_Y_R,  @"attack"  },
    { B_X,  KH_X_DX, KH_X_DY, KH_X_R, @"special" },
    { B_B,  KH_B_DX, KH_B_DY, KH_B_R, @"dash"    },
    { B_A,  KH_A_DX, KH_A_DY, KH_A_R, @"cast"    },
    { B_ZR, KH_ZR_DX, KH_ZR_DY, KH_ZR_R, @"omega" },
    { B_R,  KH_R_DX, KH_R_DY, KH_R_R, @"hex"     },
};
enum { KH_N = sizeof k_h2 / sizeof *k_h2 };
static UIImage *h2_icon(NSString *name) {   // the game's own glyph from the profile folder, if present
    NSString *p = [[NSBundle.mainBundle.resourcePath stringByAppendingPathComponent:@"dm/pad_icons"]
        stringByAppendingPathComponent:[name stringByAppendingString:@".png"]];
    return [UIImage imageWithContentsOfFile:p];
}

@interface DmGamepad : UIView
@end
static __weak DmGamepad *g_view;

@implementation DmGamepad {
    NSMapTable<UITouch *, NSNumber *> *_owner;     // touch → control (with the key for C_BTN / C_H2KEY or the stick for C_STICK, << 8)
    UITouch *_stick[2]; CGPoint _stickNow[2];      // the touch holding each stick and where it is now (0 left, 1 right)
    uint64_t _faceBits, _dpadBits, _btnBits;
    NSMapTable<UITouch *, NSNumber *> *_faceOf;    // which keys each touch on the diamond currently holds
    CAShapeLayer *_key[B_N]; CATextLayer *_label[B_N];   // one layer per key
    CAShapeLayer *_ring[2], *_knob[2];
    CAShapeLayer *_swap; CATextLayer *_swapLabel; BOOL _swapHeld;
    BOOL _sticksShown;                             // a stick was held at the last refresh
    BOOL _full;                                    // the 3D layout is current
    BOOL _h2;                                      // the Hades II layout is current
    CALayer *_controls;                            // holds every control layer: hidden while a physical controller is connected (the view itself stays, for game touches)
    BOOL _padOff;                                  // a physical controller is connected: every touch goes to the game
    UITouch *_game[16];                            // touches on the game's touch screen by finger slot
    // ---- Hades II state ----
    CAShapeLayer *_h2key[KH_N]; CALayer *_h2icon[KH_N];   // combat keys: ring + the game's glyph (or the letter label when no glyph ships)
    CATextLayer *_h2label[KH_N];
    CAShapeLayer *_h2ring, *_h2knob;                      // the floating base and its knob (own layers: reusing _ring[0] hid the 2D/3D stick)
    UITouch *_h2stick;                             // the finger holding the floating stick
    CGPoint _h2origin, _h2now;                     // the base centre (the touch-down point) and the finger now
    CGPoint _h2lostOrigin; double _h2lostS;        // the base centre and time of a cancelled stick finger (for the resume)
    BOOL _h2stickShown;                            // the floating base was drawn at the last refresh
    BOOL _h2omega;                                 // the Ω latch is armed: the next attack / special carries ZR
    double _h2omegaSince;                          // when the latch went down (the lead time runs from it)
    double _h2keyDown[KH_N];                       // when each key's finger went down (0 = up; Ω needs the duration)
    uint64_t _h2bits;                              // the combat-key bits as published at the last recompute
    // ---- Hades II menu pad ----
    BOOL _h2menu;                                  // the menu pad is expanded
    CAShapeLayer *_h2menuKey[6]; CATextLayer *_h2menuLabel[6];   // up / down / left / right / L / R
    CAShapeLayer *_h2menuHandle; CATextLayer *_h2menuHandleLabel;
    NSDate *_h2menuTouch;                          // the last touch on the menu pad (auto-hide after KH_MENU_HIDE_S)
}

static UIColor *k_idle, *k_on, *k_line, *k_ringFill, *k_text, *k_textOn;
static CAShapeLayer *shape(CALayer *parent) {
    CAShapeLayer *l = [CAShapeLayer layer];
    l.fillColor = k_idle.CGColor; l.strokeColor = k_line.CGColor; l.lineWidth = 1.5;
    l.shadowColor = UIColor.blackColor.CGColor; l.shadowOpacity = 0.2; l.shadowRadius = 3; l.shadowOffset = CGSizeMake(0, 1);
    [parent addSublayer:l]; return l;
}
static CATextLayer *label(CALayer *parent, NSString *s) {
    CATextLayer *t = [CATextLayer layer];
    t.string = s; t.alignmentMode = kCAAlignmentCenter; t.foregroundColor = k_text.CGColor; t.contentsScale = UIScreen.mainScreen.scale;
    [parent addSublayer:t]; return t;
}
static BOOL fullOnly(int b) { return b == B_LS || b == B_RS || b >= B_LEFT; }   // keys shown only in the 3D layout

- (instancetype)initWithFrame:(CGRect)f {
    if ((self = [super initWithFrame:f])) {
        self.multipleTouchEnabled = YES; self.opaque = NO; self.backgroundColor = UIColor.clearColor;
        _owner = [NSMapTable strongToStrongObjectsMapTable]; _faceOf = [NSMapTable strongToStrongObjectsMapTable];
        static dispatch_once_t once;
        dispatch_once(&once, ^{
            // each colour carries its own low opacity instead of lowering the whole view's alpha (that would add an off-screen pass for the full-screen layer)
            k_idle = [UIColor colorWithWhite:1 alpha:0.14]; k_on = [UIColor colorWithWhite:1 alpha:0.45]; k_line = [UIColor colorWithWhite:1 alpha:0.38];
            k_ringFill = [UIColor colorWithWhite:1 alpha:0.06]; k_text = [UIColor colorWithWhite:1 alpha:0.6]; k_textOn = [UIColor colorWithWhite:0 alpha:0.7];
        });
        _controls = [CALayer layer]; [self.layer addSublayer:_controls];
        for (int i = 0; i < 2; i++) {
            _ring[i] = shape(_controls); _ring[i].fillColor = k_ringFill.CGColor;
            _knob[i] = shape(_controls);
            CAShapeLayer *in = [CAShapeLayer layer]; in.fillColor = nil; in.strokeColor = k_line.CGColor; in.lineWidth = 1.5;   // inner ring of the knob
            [_knob[i] addSublayer:in];
        }
        static NSString *const names[B_N] = {@"A", @"B", @"X", @"Y", @"L3", @"R3", @"L", @"R", @"ZL", @"ZR", @"+", @"−"};
        for (int b = 0; b < B_N; b++) {
            _key[b] = shape(_controls);
            if (names[b]) _label[b] = label(_key[b], names[b]);   // the D-pad arms carry no label
        }
        _swap = shape(_controls); _swapLabel = label(_swap, @"");
        // Hades II combat keys: one ring + one content layer each; the content is the game's own
        // glyph when the profile ships one, else the button letter.
        static NSString *const h2names[KH_N] = {@"Y", @"X", @"B", @"A", @"Ω", @"R"};
        for (int i = 0; i < KH_N; i++) {
            _h2key[i] = shape(_controls);
            UIImage *im = h2_icon(k_h2[i].icon);
            if (im) {
                _h2icon[i] = [CALayer layer]; _h2icon[i].contents = (__bridge id)im.CGImage;
                _h2icon[i].contentsGravity = kCAGravityResizeAspect;
                [_h2key[i] addSublayer:_h2icon[i]];
            } else {
                _h2label[i] = label(_h2key[i], h2names[i]);
            }
        }
        NSNumber *saved = [NSUserDefaults.standardUserDefaults objectForKey:k_layout_key];
        _full = saved ? saved.boolValue : DM_GAME_PAD_FULL;
        NSNumber *h2saved = [NSUserDefaults.standardUserDefaults objectForKey:k_h2_key];
        _h2 = h2saved ? h2saved.boolValue : NO;
        // The floating base and knob: own layers, not the fixed stick's — sharing them hid the 2D/3D stick.
        _h2ring = shape(_controls); _h2ring.fillColor = k_ringFill.CGColor;
        _h2knob = shape(_controls);
        CAShapeLayer *h2in = [CAShapeLayer layer]; h2in.fillColor = nil; h2in.strokeColor = k_line.CGColor; h2in.lineWidth = 1.5;
        [_h2knob addSublayer:h2in];
        // The menu pad: a handle on the left edge expands a small D-pad + L / R for the menus.
        _h2menuHandle = shape(_controls);
        _h2menuHandleLabel = label(_h2menuHandle, @"☰");
        static NSString *const h2menuNames[6] = {@"↑", @"↓", @"←", @"→", @"L", @"R"};
        for (int i = 0; i < 6; i++) {
            _h2menuKey[i] = shape(_controls); _h2menuKey[i].hidden = YES;
            _h2menuLabel[i] = label(_h2menuKey[i], h2menuNames[i]);
        }
        _h2menuHandle.hidden = YES;   // only the H2 layout shows it
        [self applyLayout];
        NSNotificationCenter *nc = NSNotificationCenter.defaultCenter;
        [nc addObserver:self selector:@selector(padsChanged) name:GCControllerDidConnectNotification object:nil];
        [nc addObserver:self selector:@selector(padsChanged) name:GCControllerDidDisconnectNotification object:nil];
        [self padsChanged];
    }
    return self;
}
- (void)applyLayout {   // show / hide the controls for the current layout
    [CATransaction begin]; [CATransaction setDisableActions:YES];
    for (int b = 0; b < B_N; b++) _key[b].hidden = _h2 || (fullOnly(b) && !_full);
    _ring[1].hidden = _knob[1].hidden = _h2 || !_full;
    _ring[0].hidden = _knob[0].hidden = _h2;         // the H2 stick has its own floating base layers
    for (int i = 0; i < KH_N; i++) _h2key[i].hidden = !_h2;
    _h2menuHandle.hidden = !_h2;                     // the handle always shows in H2; the pad expands on tap
    if (!_h2) _h2menu = NO;
    for (int i = 0; i < 6; i++) _h2menuKey[i].hidden = !_h2 || !_h2menu;
    _swapLabel.string = _h2 ? @"H2" : _full ? @"3D" : @"2D";
    [CATransaction commit];
}
- (void)setFull:(BOOL)full {   // cycle layouts: 2D → 3D → H2 → 2D. Release every touch first (no key stays held), save, lay out again
    if (full) {
        if (!_full) { [self reset]; _full = YES; _h2 = NO; }
        else if (!_h2) { [self reset]; _h2 = YES; }
        else { [self reset]; _full = NO; _h2 = NO; }
    } else {
        if (!_full && !_h2) { [self reset]; _full = YES; }
        else { [self reset]; _full = NO; _h2 = NO; }
    }
    [NSUserDefaults.standardUserDefaults setObject:@(_full) forKey:k_layout_key];
    [NSUserDefaults.standardUserDefaults setObject:@(_h2) forKey:k_h2_key];
    [self applyLayout]; [self setNeedsLayout];
}

// ---- Layout (points; computed inside the safe area) ----
- (CGRect)safe { return UIEdgeInsetsInsetRect(self.bounds, self.safeAreaInsets); }
- (CGRect)corner { UIEdgeInsets i = self.safeAreaInsets; i.left *= K_CORNER_IN; i.right *= K_CORNER_IN; return UIEdgeInsetsInsetRect(self.bounds, i); }   // the rectangle the bottom-corner controls use
- (CGFloat)u { return MIN(self.bounds.size.height / 430.0, 1.3); }   // 1 = 430 points tall (iPhone Pro Max landscape)
static CGPoint side(CGRect s, int right, CGFloat dx, CGFloat y) { return CGPointMake(right ? CGRectGetMaxX(s) - dx : CGRectGetMinX(s) + dx, y); }
- (CGPoint)faceCenter { CGRect s = self.corner; CGFloat u = self.u; return side(s, 1, K_FACE_X * u, CGRectGetMaxY(s) - K_PAD_Y * u); }
- (CGFloat)faceGap { return K_FACE_GAP * self.u; }
- (CGFloat)faceR { return K_FACE_R * self.u; }
- (CGPoint)facePos:(int)b { CGPoint c = self.faceCenter; CGFloat g = self.faceGap;
    switch (b) { case B_A: return CGPointMake(c.x + g, c.y); case B_B: return CGPointMake(c.x, c.y + g); case B_X: return CGPointMake(c.x, c.y - g); default: return CGPointMake(c.x - g, c.y); } }
- (CGPoint)stickHome:(int)i { CGRect s = self.corner; CGFloat u = self.u;
    return i ? side(s, 1, K_LOW_X * u, CGRectGetMaxY(s) - K_LOW_Y * u) : side(s, 0, K_STICK_X * u, CGRectGetMaxY(s) - K_PAD_Y * u); }
- (CGFloat)stickR:(int)i { return (i ? K_RSTICK_R : K_STICK_R) * self.u; }
- (CGPoint)dpadCenter { CGRect s = self.corner; CGFloat u = self.u; return side(s, 0, K_LOW_X * u, CGRectGetMaxY(s) - K_LOW_Y * u); }
- (CGFloat)dpadR { return K_DPAD_R * self.u; }
static BOOL isDrop(int b) { return b == B_ZL || b == B_L || b == B_ZR || b == B_R; }
static BOOL isClick(int b) { return b == B_LS || b == B_RS; }
- (CGPoint)dropCenter:(int)b { CGRect s = self.safe; CGFloat u = self.u; BOOL z = b == B_ZL || b == B_ZR;
    return side(s, b == B_ZR || b == B_R, (z ? K_ZL_X : K_L_X) * u, CGRectGetMinY(s) + (z ? K_ZL_Y : K_L_Y) * u); }
- (CGFloat)dropR:(int)b { return (b == B_ZL || b == B_ZR ? K_ZL_R : K_L_R) * self.u; }
- (CGPoint)clickCenter:(int)b { CGRect s = self.safe; CGFloat u = self.u; return side(s, b == B_RS, K_CLICK_X * u, CGRectGetMinY(s) + K_ZL_Y * u); }
- (CGRect)pillRect:(int)b { CGRect s = self.safe; CGFloat u = self.u, w = K_PILL_W * u, h = K_PILL_H * u;
    CGPoint c = CGPointMake(CGRectGetMidX(s) + (b == B_PLUS ? K_PILL_DX : -K_PILL_DX) * u, CGRectGetMinY(s) + K_PILL_Y * u);   // − on the left, + on the right
    return CGRectMake(c.x - w / 2, c.y - h / 2, w, h); }
- (CGPoint)swapCenter { CGRect s = self.safe; return CGPointMake(CGRectGetMidX(s), CGRectGetMinY(s) + K_PILL_Y * self.u); }

// ---- Hades II geometry ----
- (CGFloat)h2u {   // the H2 layout scales by the SHORT screen edge, tighter than the global u:
    // the key cluster spans about 320 u horizontally (Y anchor + A/R inward + ZR up), and it must
    // fit half the screen next to the stick zone on every iPhone (smallest landscape height 375).
    CGFloat byHeight = self.bounds.size.height / 430.0, byWidth = self.bounds.size.width / 932.0;
    return fmin(fmin(byHeight, byWidth), 1.3) * fmin(1.0, self.bounds.size.width * 0.5 / 340.0);
}
- (CGPoint)h2Anchor {   // Y, the anchor every other key is placed from
    CGRect s = self.corner; CGFloat u = self.h2u;
    return side(s, 1, KH_FACE_X * u, CGRectGetMaxY(s) - KH_FACE_Y * u);
}
- (CGPoint)h2keyCenter:(int)i {
    CGPoint a = self.h2Anchor; CGFloat u = self.h2u;
    return CGPointMake(a.x + k_h2[i].dx * u, a.y + k_h2[i].dy * u);
}
- (CGFloat)h2keyR:(int)i { return k_h2[i].r * self.h2u; }
- (int)h2keyAt:(CGPoint)p {
    for (int i = 0; i < KH_N; i++) { CGFloat r = [self h2keyR:i] * 1.18;   // a slightly generous hit area: small keys must not need pixel aim
        if (dist(p, [self h2keyCenter:i]) <= r) return i; }
    return -1;
}
// ---- Hades II menu pad geometry ----
- (CGPoint)h2menuHandleCenter {
    CGFloat u = self.h2u;
    return CGPointMake(CGRectGetMinX(self.safe) + KH_MENU_HANDLE_X * u, self.bounds.size.height * KH_MENU_HANDLE_Y);
}
- (CGFloat)h2menuHandleR { return KH_MENU_HANDLE_R * self.h2u; }
- (CGPoint)h2menuCenter {
    CGFloat u = self.h2u;
    return CGPointMake(CGRectGetMinX(self.safe) + KH_MENU_X * u, self.bounds.size.height * KH_MENU_Y);
}
- (CGFloat)h2menuR { return KH_MENU_R * self.h2u; }
- (CGPoint)h2menuBumper:(int)i {   // 4 = L (above), 5 = R (below)
    CGPoint c = self.h2menuCenter; CGFloat u = self.h2u;
    CGFloat dy = i == 4 ? KH_MENU_L_DY : KH_MENU_R_DY;
    return CGPointMake(c.x + KH_MENU_L_DX * u, c.y + dy * u);
}
- (int)h2menuAt:(CGPoint)p {   // 0 up, 1 down, 2 left, 3 right, 4 L, 5 R; -1 none
    CGFloat r = self.h2menuR * 1.15;
    for (int i = 0; i < 4; i++) {
        static const CGFloat an[4] = {-M_PI_2, M_PI_2, M_PI, 0};
        CGPoint c = CGPointMake(self.h2menuCenter.x + self.h2menuR * cos(an[i]), self.h2menuCenter.y + self.h2menuR * sin(an[i]));
        if (dist(p, c) <= self.h2menuR * 0.62) return i;
    }
    for (int i = 4; i < 6; i++) if (dist(p, [self h2menuBumper:i]) <= self.h2menuR * 0.55) return i;
    return -1;
}
- (BOOL)h2inMenuHandle:(CGPoint)p { return dist(p, [self h2menuHandleCenter]) <= [self h2menuHandleR] * 1.5; }
- (BOOL)h2inStickZone:(CGPoint)p {   // the lower-left zone the floating stick starts in
    return p.x >= 0 && p.y <= self.bounds.size.height
        && p.x < self.bounds.size.width * KH_ZONE_R
        && p.y > self.bounds.size.height * (1 - KH_ZONE_T);
}
// The knob offset from the floating base (clamped to the base edge), the same convention as knobOffset.
- (CGPoint)h2knobOffset {
    if (!_h2stick) return CGPointZero;
    CGFloat dx = _h2now.x - _h2origin.x, dy = _h2now.y - _h2origin.y, d = hypot(dx, dy), R = KH_STICK_R * self.h2u;
    if (d > R) { dx *= R / d; dy *= R / d; }
    return CGPointMake(dx, dy);
}

static CGFloat dist(CGPoint a, CGPoint b) { return hypot(a.x - b.x, a.y - b.y); }
- (int)btnAt:(CGPoint)p {   // locked keys (tested on touch-down only, then locked)
    CGFloat u = self.u;
    for (int i = 0; i < (int)(sizeof k_btns / sizeof *k_btns); i++) { int b = k_btns[i];
        if (fullOnly(b) && !_full) continue;
        BOOL hit = isDrop(b) ? dist(p, [self dropCenter:b]) <= [self dropR:b] * 1.35
                 : isClick(b) ? dist(p, [self clickCenter:b]) <= K_CLICK_R * u * 1.35
                 : CGRectContainsPoint(CGRectInset([self pillRect:b], -8 * u, -8 * u), p);
        if (hit) return b; }
    return -1;
}
- (BOOL)inSwap:(CGPoint)p { return dist(p, self.swapCenter) <= K_SWAP_R * self.u * 1.6; }
- (uint64_t)faceAt:(CGPoint)p {   // keys under the finger in the diamond (between two keys both count)
    uint64_t m = 0; CGFloat r = self.faceR * 1.25;
    for (int b = B_A; b <= B_Y; b++) if (dist(p, [self facePos:b]) <= r) m |= 1ull << b;
    return m;
}
- (uint64_t)dpadAt:(CGPoint)p {   // 8 directions: 45° each, diagonals press two keys; a small centre circle counts as none
    CGPoint c = self.dpadCenter; CGFloat dx = p.x - c.x, dy = p.y - c.y;
    if (hypot(dx, dy) < self.dpadR * 0.25) return 0;
    double a = atan2(-dy, dx) * 180 / M_PI; uint64_t m = 0;
    if (a > -67.5 && a < 67.5) m |= 1ull << B_RIGHT;
    if (a > 22.5 && a < 157.5) m |= 1ull << B_UP;
    if (a > 112.5 || a < -112.5) m |= 1ull << B_LEFT;
    if (a < -22.5 && a > -157.5) m |= 1ull << B_DOWN;
    return m;
}
- (CGPoint)knobOffset:(int)i {   // knob offset from the ring centre (clamped to the ring)
    if (!_stick[i]) return CGPointZero;
    CGPoint h = [self stickHome:i]; CGFloat dx = _stickNow[i].x - h.x, dy = _stickNow[i].y - h.y, d = hypot(dx, dy), R = [self stickR:i];
    if (d > R) { dx *= R / d; dy *= R / d; }
    return CGPointMake(dx, dy);
}

// ---- Touch ----
- (void)recompute {
    uint64_t face = 0; for (UITouch *t in _faceOf) face |= [_faceOf objectForKey:t].unsignedLongLongValue;
    uint64_t btn = 0, dpad = 0; BOOL swap = NO;
    for (UITouch *t in _owner) { uint64_t v = [_owner objectForKey:t].unsignedLongLongValue; int c = (int)(v & 0xff);
        if (c == C_BTN) btn |= 1ull << (v >> 8);
        else if (c == C_DPAD) dpad |= [self dpadAt:[t locationInView:self]];
        else if (c == C_SWAP) swap = YES; }
    int32_t ax[4] = {0};
    for (int i = 0; i < 2; i++) {
        CGPoint o = [self knobOffset:i]; CGFloat R = [self stickR:i], d = hypot(o.x, o.y), dz = R * K_DEAD;
        if (d <= dz) continue;
        CGFloat m = fmin((d - dz) / (R * K_FULL - dz), 1) / d;   // outside the dead zone: 0 rising to full at the full-tilt radius
        ax[i * 2] = (int32_t)lrint(o.x * m * 32767); ax[i * 2 + 1] = (int32_t)lrint(-o.y * m * 32767);   // host: up is positive; rounded so full tilt is exactly 32767
    }
    // Hades II combat keys: the bits from every finger on an H2 key, plus the Ω latch. The latch
    // leads the attack / special by KH_ZR_LEAD: when a key that carries ZR goes down within the
    // lead window of the latch, the published button set waits the remainder before adding it, so
    // a quick tap-Ω-attack still arrives in the game's own "hold ZR first" order. Press durations
    // pass through untouched (the Ω moves are holds; the hex's hold-and-release works as is).
    uint64_t h2 = 0;
    static const int h2menuBtn[6] = {B_UP, B_DOWN, B_LEFT, B_RIGHT, B_L, B_R};
    for (UITouch *t in _owner) { uint64_t v = [_owner objectForKey:t].unsignedLongLongValue;
        if ((v & 0xff) != C_H2KEY) continue;
        int tag = (int)(v >> 8);
        if (tag < KH_N) h2 |= 1ull << k_h2[tag].b;
        else if (tag >= KH_N + 16) h2 |= 1ull << h2menuBtn[tag - KH_N - 16];
        /* the handle's tag (KH_N + 8) holds no key: the toggle happened at touch-down */ }
    // the menu pad hides itself when nothing has touched it for a while
    if (_h2menu && _h2menuTouch && [_h2menuTouch timeIntervalSinceNow] < -KH_MENU_HIDE_S) {
        _h2menu = NO; [self applyLayout];
    }
    BOOL h2changed = h2 != _h2bits;
    _h2bits = h2;
    // The H2 floating stick: axis values from the finger's offset to the base centre (the same
    // curve as the fixed sticks — dead zone, then rising to full at KH_FULL of the base radius).
    if (_h2 && _h2stick) {
        CGPoint o = [self h2knobOffset]; CGFloat R = KH_STICK_R * self.h2u, d = hypot(o.x, o.y), dz = R * KH_DEAD;
        if (d > dz) {
            CGFloat m = fmin((d - dz) / (R * KH_FULL - dz), 1) / d;
            ax[0] = (int32_t)lrint(o.x * m * 32767); ax[1] = (int32_t)lrint(-o.y * m * 32767);
        }
    }
    if (_h2 && _h2omega) {
        // A ZR-carrying key is down (or comes down): ZR leads it by the remainder of the window.
        BOOL carry = (h2 & ((1ull << B_Y) | (1ull << B_X))) != 0;
        double now = [NSDate timeIntervalSinceReferenceDate];
        if (carry && now - _h2omegaSince < KH_ZR_LEAD) {
            double left = KH_ZR_LEAD - (now - _h2omegaSince);
            dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(left * NSEC_PER_SEC)),
                           dispatch_get_main_queue(), ^{ [self recompute]; });
        } else if (carry || now - _h2omegaSince >= KH_ZR_LEAD) {
            h2 |= 1ull << B_ZR;
        }
    }
    BOOL changed = face != _faceBits || dpad != _dpadBits || btn != _btnBits || swap != _swapHeld || h2changed;
    _faceBits = face; _dpadBits = dpad; _btnBits = btn; _swapHeld = swap;
    pthread_mutex_lock(&g_mu);
    if (_h2) { g_touch_btn = h2 | btn; g_touch_lx = ax[0]; g_touch_ly = ax[1]; g_touch_rx = 0; g_touch_ry = 0; }
    else { g_touch_btn = face | dpad | btn; g_touch_lx = ax[0]; g_touch_ly = ax[1]; g_touch_rx = ax[2]; g_touch_ry = ax[3]; }
    pthread_mutex_unlock(&g_mu);
    publish();
    BOOL sticks = _h2 ? _h2stick != nil : (_stick[0] || _stick[1]);
    if (changed || sticks || _sticksShown) [self refresh];   // also refresh on the stick release so the knob returns to the centre
    _sticksShown = sticks;
}
// Touches no control takes (all of them while a physical controller is connected) go to the game's touch screen, normalized on the 16:9 picture that front_ios.m
// centres in the screen: Super Mario Galaxy's pointer in handheld mode (profile op_mode). The host reports them only in handheld mode, as on the Switch (hle_hid.c touch_read)
- (void)pushGame {
    CGRect b = self.bounds; CGFloat w = b.size.width, h = b.size.height;
    if (w <= 0 || h <= 0) return;
    if (w / h > 16.0 / 9.0) w = h * 16.0 / 9.0; else h = w * 9.0 / 16.0;
    CGFloat x0 = (b.size.width - w) / 2, y0 = (b.size.height - h) / 2;
    dm_touch t[16]; int n = 0;
    for (int i = 0; i < 16; i++) if (_game[i]) {
        CGPoint p = [_game[i] locationInView:self];
        t[n++] = (dm_touch){(uint32_t)i, (float)fmin(fmax((p.x - x0) / w, 0), 0.999), (float)fmin(fmax((p.y - y0) / h, 0), 0.999)};
    }
    dm_touch_set(t, n);
}
- (BOOL)gameBegin:(UITouch *)t {
    for (int i = 0; i < 16; i++) if (!_game[i]) { _game[i] = t; [_owner setObject:@(C_GAME | (uint64_t)i << 8) forKey:t]; return YES; }
    return NO;
}
- (BOOL)touchesBeganH2:(NSSet<UITouch *> *)ts {
    BOOL game = NO;
    for (UITouch *t in ts) {
        CGPoint p = [t locationInView:self];
        // locked keys first (shoulders, − / +, the layout button), then H2 keys, then the menu pad, then the stick zone
        int hit = [self btnAt:p];
        if (hit >= 0) { [_owner setObject:@(C_BTN | (uint64_t)hit << 8) forKey:t]; continue; }
        if ([self inSwap:p]) { [_owner setObject:@(C_SWAP) forKey:t]; continue; }
        if ([self h2inMenuHandle:p]) {   // the handle toggles the menu pad on touch-down
            _h2menu = !_h2menu; _h2menuTouch = [NSDate date]; [self applyLayout];
            [_owner setObject:@(C_H2KEY | (uint64_t)(KH_N + 8) << 8) forKey:t];   // holds no key
            continue;
        }
        if (_h2menu) {
            int m = [self h2menuAt:p];
            if (m >= 0) {
                [_owner setObject:@(C_H2KEY | (uint64_t)(KH_N + 16 + m) << 8) forKey:t];
                _h2menuTouch = [NSDate date];
                continue;
            }
        }
        int k = [self h2keyAt:p];
        if (k >= 0) {
            [_owner setObject:@(C_H2KEY | (uint64_t)k << 8) forKey:t];
            _h2keyDown[k] = [NSDate timeIntervalSinceReferenceDate];
            if (k_h2[k].b == B_ZR) { _h2omega = YES; _h2omegaSince = _h2keyDown[k]; }   // the Ω latch arms
            continue;
        }
        // The floating stick: a touch in the lower-left zone starts it, base centre = the touch
        // point (clamped so the base stays on screen). A finger resuming after a system cancel
        // keeps the old base instead of jumping to the new touch point.
        if (!_h2stick && [self h2inStickZone:p]) {
            BOOL resume = _h2lostS > 0 && [NSDate timeIntervalSinceReferenceDate] - _h2lostS <= KH_RESUME_S
                && dist(p, CGPointMake(_h2lostOrigin.x, _h2lostOrigin.y)) <= KH_RESUME_K * KH_STICK_R * self.h2u;
            _h2stick = t; _h2now = p;
            if (resume) _h2origin = _h2lostOrigin;
            else {
                CGFloat R = KH_STICK_R * self.h2u, m = CGRectGetMinX(self.bounds) + R + 8;
                _h2origin = CGPointMake(fmax(p.x, m), fmin(p.y, self.bounds.size.height - R - 8));
            }
            _h2lostS = 0;
            [_owner setObject:@(C_STICK | (uint64_t)2 << 8) forKey:t];   // slot 2 = the H2 floating stick
            continue;
        }
        game |= [self gameBegin:t];
    }
    return game;
}
- (BOOL)touchesMovedH2:(NSSet<UITouch *> *)ts {
    BOOL game = NO;
    for (UITouch *t in ts) {
        uint64_t v = [_owner objectForKey:t].unsignedLongLongValue;
        if ((v & 0xff) == C_STICK && (v >> 8) == 2) _h2now = [t locationInView:self];
        else if ((v & 0xff) == C_GAME) game = YES;
    }
    return game;
}
- (void)touchesBegan:(NSSet<UITouch *> *)ts withEvent:(UIEvent *)e {
    BOOL game = NO;
    if (_padOff) { for (UITouch *t in ts) game |= [self gameBegin:t]; }
    else if (_h2) game = [self touchesBeganH2:ts];
    else for (UITouch *t in ts) {
        CGPoint p = [t locationInView:self]; int hit = [self btnAt:p];
        if (hit >= 0) { [_owner setObject:@(C_BTN | (uint64_t)hit << 8) forKey:t]; continue; }
        if ([self inSwap:p]) { [_owner setObject:@(C_SWAP) forKey:t]; continue; }
        // diamond, D-pad, the two sticks: take the one with the smallest distance / grab radius, if it is <= 1
        CGFloat best = 1; int kind = C_NONE, idx = 0;
        CGFloat f = dist(p, self.faceCenter) / (self.faceGap + self.faceR * 1.6); if (f <= best) { best = f; kind = C_FACE; }
        if (_full) { CGFloat d = dist(p, self.dpadCenter) / (self.dpadR * K_DPAD_GRAB); if (d < best) { best = d; kind = C_DPAD; } }
        for (int i = 0; i < (_full ? 2 : 1); i++) if (!_stick[i]) {
            CGFloat s = dist(p, [self stickHome:i]) / ([self stickR:i] * K_STICK_GRAB); if (s < best) { best = s; kind = C_STICK; idx = i; } }
        if (kind == C_FACE) { [_owner setObject:@(C_FACE) forKey:t]; [_faceOf setObject:@([self faceAt:p]) forKey:t]; }
        else if (kind == C_DPAD) [_owner setObject:@(C_DPAD) forKey:t];
        else if (kind == C_STICK) { [_owner setObject:@(C_STICK | (uint64_t)idx << 8) forKey:t]; _stick[idx] = t; _stickNow[idx] = p; }
        else game |= [self gameBegin:t];
    }
    if (game) [self pushGame];
    [self recompute];
}
- (void)touchesMoved:(NSSet<UITouch *> *)ts withEvent:(UIEvent *)e {
    BOOL game = NO;
    if (_h2) game = [self touchesMovedH2:ts];
    else for (UITouch *t in ts) {
        uint64_t v = [_owner objectForKey:t].unsignedLongLongValue; int c = (int)(v & 0xff); CGPoint p = [t locationInView:self];
        if (c == C_FACE) [_faceOf setObject:@([self faceAt:p]) forKey:t];
        else if (c == C_STICK) _stickNow[v >> 8] = p;
        else if (c == C_GAME) game = YES;
    }
    if (game) [self pushGame];
    [self recompute];
}
- (void)endTouches:(NSSet<UITouch *> *)ts tapped:(BOOL)ended {
    BOOL swap = NO, game = NO;
    for (UITouch *t in ts) {
        uint64_t v = [_owner objectForKey:t].unsignedLongLongValue;
        if (ended && (v & 0xff) == C_SWAP && [self inSwap:[t locationInView:self]]) swap = YES;   // layout button: counts only when released on the button
        if ((v & 0xff) == C_STICK && (v >> 8) == 2 && t == _h2stick) {   // the floating stick: record for the resume
            _h2stick = nil; _h2lostOrigin = _h2origin; _h2lostS = [NSDate timeIntervalSinceReferenceDate];
        }
        if ((v & 0xff) == C_H2KEY) {
            int tag = (int)(v >> 8);
            if (tag < KH_N) { _h2keyDown[tag] = 0; if (k_h2[tag].b == B_ZR) _h2omega = NO; }
            else if (tag >= KH_N + 16 && ended) {   // a menu key: touch the auto-hide clock
                _h2menuTouch = [NSDate date];
            }
            // the handle's toggle happens in recompute (it sees the release through the missing bit)
        }
        if ((v & 0xff) == C_GAME && (v >> 8) < 16) { _game[v >> 8] = nil; game = YES; }
        [_owner removeObjectForKey:t]; [_faceOf removeObjectForKey:t]; for (int i = 0; i < 2; i++) if (t == _stick[i]) _stick[i] = nil;
    }
    if (game) [self pushGame];
    [self recompute];
    if (swap) [self setFull:YES];   // cycle 2D → 3D → H2 → 2D
}
- (void)touchesEnded:(NSSet<UITouch *> *)ts withEvent:(UIEvent *)e { [self endTouches:ts tapped:YES]; }
- (void)touchesCancelled:(NSSet<UITouch *> *)ts withEvent:(UIEvent *)e { [self endTouches:ts tapped:NO]; }
- (void)reset { [_owner removeAllObjects]; [_faceOf removeAllObjects]; _stick[0] = _stick[1] = nil; for (int i = 0; i < 16; i++) _game[i] = nil;
    _h2stick = nil; _h2omega = NO; for (int i = 0; i < KH_N; i++) _h2keyDown[i] = 0; _h2lostS = 0; _h2menu = NO; [self pushGame]; [self recompute]; }

// ---- Shapes ----
static CGPathRef circlePath(CGPoint c, CGFloat r) { return CGPathCreateWithEllipseInRect(CGRectMake(c.x - r, c.y - r, 2 * r, 2 * r), NULL); }
static CGPathRef dropPath(CGPoint c, CGFloat r, CGFloat tipAngle, CGFloat round) {   // teardrop: circle + two tangents meeting at the tip, tip slightly rounded
    CGFloat d = r * K_DROP_TIP, th = acos(r / d);
    CGPoint tip = CGPointMake(c.x + d * cos(tipAngle), c.y + d * sin(tipAngle));
    CGPoint p1 = CGPointMake(c.x + r * cos(tipAngle + th), c.y + r * sin(tipAngle + th)), p2 = CGPointMake(c.x + r * cos(tipAngle - th), c.y + r * sin(tipAngle - th));
    CGMutablePathRef p = CGPathCreateMutable();
    CGPathMoveToPoint(p, NULL, p2.x, p2.y);
    CGPathAddArcToPoint(p, NULL, tip.x, tip.y, p1.x, p1.y, round);
    CGPathAddArc(p, NULL, c.x, c.y, r, tipAngle + th, tipAngle - th + 2 * M_PI, false);
    CGPathCloseSubpath(p); return p;
}
static CGPathRef armPath(CGPoint c, CGFloat R, CGFloat w, CGFloat in, CGFloat angle, CGFloat round) {   // one D-pad arm: an upward pentagon (tip toward the centre) rotated by angle around the centre
    CGPoint v[5] = {{-w, -R}, {w, -R}, {w, -(in + w)}, {0, -in}, {-w, -(in + w)}};
    CGFloat cs = cos(angle), sn = sin(angle);
    for (int i = 0; i < 5; i++) v[i] = CGPointMake(c.x + v[i].x * cs - v[i].y * sn, c.y + v[i].x * sn + v[i].y * cs);
    CGMutablePathRef p = CGPathCreateMutable();
    CGPathMoveToPoint(p, NULL, (v[4].x + v[0].x) / 2, (v[4].y + v[0].y) / 2);
    for (int i = 0; i < 5; i++) CGPathAddArcToPoint(p, NULL, v[i].x, v[i].y, v[(i + 1) % 5].x, v[(i + 1) % 5].y, round);
    CGPathCloseSubpath(p); return p;
}
static void setPath(CAShapeLayer *l, CGPathRef p) { l.path = p; l.shadowPath = p; CGPathRelease(p); }
static void placeLabel(CATextLayer *t, CGPoint c, CGFloat fs) {
    CTFontRef f = CTFontCreateUIFontForLanguage(kCTFontUIFontEmphasizedSystem, fs, NULL);
    t.font = f; t.fontSize = fs;
    CGFloat h = CTFontGetAscent(f) + CTFontGetDescent(f) + CTFontGetLeading(f), w = fs * 3;
    t.frame = CGRectMake(c.x - w / 2, c.y - h / 2, w, h);
    CFRelease(f);
}

- (void)layoutSubviews {
    [super layoutSubviews];
    CGFloat u = self.u;
    [CATransaction begin]; [CATransaction setDisableActions:YES];
    _controls.frame = self.layer.bounds;
    for (int b = B_A; b <= B_Y; b++) { CGPoint c = [self facePos:b]; setPath(_key[b], circlePath(c, self.faceR)); placeLabel(_label[b], c, 20 * u); }
    for (int i = 0; i < (int)(sizeof k_btns / sizeof *k_btns); i++) { int b = k_btns[i];
        if (isDrop(b)) {
            BOOL right = b == B_ZR || b == B_R; CGPoint c = [self dropCenter:b];
            setPath(_key[b], dropPath(c, [self dropR:b], right ? -M_PI_4 : -3 * M_PI_4, 4 * u)); placeLabel(_label[b], c, 16 * u);   // tip toward the near top corner
        } else if (isClick(b)) {
            CGPoint c = [self clickCenter:b]; setPath(_key[b], circlePath(c, K_CLICK_R * u)); placeLabel(_label[b], c, 13 * u);
        } else {
            CGRect rc = [self pillRect:b];
            setPath(_key[b], CGPathCreateWithRoundedRect(rc, rc.size.height / 2, rc.size.height / 2, NULL)); placeLabel(_label[b], CGPointMake(CGRectGetMidX(rc), CGRectGetMidY(rc)), 18 * u);
        }
    }
    static const struct { int b; CGFloat angle; } arms[] = {{B_UP, 0}, {B_RIGHT, M_PI_2}, {B_DOWN, M_PI}, {B_LEFT, -M_PI_2}};   // the same arm in 90° steps
    for (int i = 0; i < 4; i++) setPath(_key[arms[i].b], armPath(self.dpadCenter, self.dpadR, K_ARM_W * u, K_ARM_IN * u, arms[i].angle, 6 * u));
    CGPoint sc = self.swapCenter; setPath(_swap, circlePath(sc, K_SWAP_R * u)); placeLabel(_swapLabel, sc, 12 * u);
    // Hades II combat keys: rings at their centres, the glyph (or letter) centred inside
    for (int i = 0; i < KH_N; i++) {
        CGPoint c = [self h2keyCenter:i]; CGFloat r = [self h2keyR:i];
        setPath(_h2key[i], circlePath(c, r));
        if (_h2icon[i]) {
            CGFloat s = r * 1.1;   // the glyph slightly larger than the ring's inner circle
            _h2icon[i].frame = CGRectMake(c.x - s / 2, c.y - s / 2, s, s);
        } else if (_h2label[i]) {
            placeLabel(_h2label[i], c, r * 0.75);
        }
    }
    // Hades II menu pad: the handle on the left edge; the D-pad arms and the two bumpers
    {
        CGPoint hc = [self h2menuHandleCenter]; CGFloat hr = [self h2menuHandleR];
        setPath(_h2menuHandle, circlePath(hc, hr)); placeLabel(_h2menuHandleLabel, hc, hr * 0.9);
        CGPoint c = [self h2menuCenter]; CGFloat r = self.h2menuR, arm = KH_MENU_ARM * self.h2u, tip = KH_MENU_IN * self.h2u;
        static const struct { int i, b; CGFloat angle; } arms[] = {{0, B_UP, 0}, {1, B_DOWN, M_PI}, {2, B_LEFT, -M_PI_2}, {3, B_RIGHT, M_PI_2}};
        for (int i = 0; i < 4; i++) {
            setPath(_h2menuKey[arms[i].i], armPath(c, r, arm, tip, arms[i].angle, 5 * self.h2u));
            CGPoint k = CGPointMake(c.x + r * cos(arms[i].angle), c.y + r * sin(arms[i].angle));
            placeLabel(_h2menuLabel[arms[i].i], k, 15 * self.h2u);
        }
        for (int i = 4; i < 6; i++) {
            CGPoint bc = [self h2menuBumper:i];
            setPath(_h2menuKey[i], circlePath(bc, r * 0.52));
            placeLabel(_h2menuLabel[i], bc, 16 * self.h2u);
        }
    }
    for (int i = 0; i < 2; i++) {
        setPath(_ring[i], circlePath([self stickHome:i], [self stickR:i]));
        CGFloat k = (i ? K_RKNOB_R : K_KNOB_R) * u; _knob[i].bounds = CGRectMake(0, 0, 2 * k, 2 * k);
        setPath(_knob[i], circlePath(CGPointMake(k, k), k));
        CAShapeLayer *in = (CAShapeLayer *)_knob[i].sublayers.firstObject; CGPathRef ip = circlePath(CGPointMake(k, k), k * 0.62);
        in.frame = _knob[i].bounds; in.path = ip; CGPathRelease(ip);
    }
    [CATransaction commit];
    [self refresh];
}
- (void)safeAreaInsetsDidChange { [super safeAreaInsetsDidChange]; [self setNeedsLayout]; }
- (void)refresh {   // pressed state → fill, sticks → knob position
    uint64_t all = _faceBits | _dpadBits | _btnBits | (_h2 ? _h2bits : 0);
    [CATransaction begin]; [CATransaction setDisableActions:YES];
    for (int b = 0; b < B_N; b++) { BOOL on = (all >> b) & 1;
        _key[b].fillColor = (on ? k_on : k_idle).CGColor; _label[b].foregroundColor = (on ? k_textOn : k_text).CGColor; }
    _swap.fillColor = (_swapHeld ? k_on : k_idle).CGColor; _swapLabel.foregroundColor = (_swapHeld ? k_textOn : k_text).CGColor;
    for (int i = 0; i < KH_N; i++) {
        BOOL on = (_h2bits >> k_h2[i].b) & 1;
        BOOL armed = _h2 && k_h2[i].b == B_ZR && _h2omega;   // the Ω latch glows while armed
        _h2key[i].fillColor = (on || armed ? k_on : k_idle).CGColor;
        if (_h2label[i]) _h2label[i].foregroundColor = (on || armed ? k_textOn : k_text).CGColor;
    }
    // the menu pad: handle always visible in H2; the expanded keys light on press
    _h2menuHandle.fillColor = (_h2menu ? k_on : k_idle).CGColor; _h2menuHandleLabel.foregroundColor = (_h2menu ? k_textOn : k_text).CGColor;
    {
        static const int h2menuBtn[6] = {B_UP, B_DOWN, B_LEFT, B_RIGHT, B_L, B_R};
        for (int i = 0; i < 6; i++) {
            BOOL on = (_h2bits >> h2menuBtn[i]) & 1;
            _h2menuKey[i].fillColor = (on ? k_on : k_idle).CGColor;
            _h2menuLabel[i].foregroundColor = (on ? k_textOn : k_text).CGColor;
        }
    }
    for (int i = 0; i < 2; i++) {
        CGPoint h = [self stickHome:i], o = [self knobOffset:i];
        _knob[i].position = CGPointMake(h.x + o.x, h.y + o.y); _knob[i].fillColor = (_stick[i] ? k_on : k_idle).CGColor;
    }
    // the H2 floating base: hidden with no stick finger, drawn at its origin with the knob when held
    BOOL h2s = _h2 && _h2stick != nil;
    _h2ring.hidden = !h2s; _h2knob.hidden = !h2s;
    if (h2s) {
        CGFloat R = KH_STICK_R * self.h2u, k = K_KNOB_R * self.u;
        setPath(_h2ring, circlePath(_h2origin, R));
        _h2knob.bounds = CGRectMake(0, 0, 2 * k, 2 * k);
        setPath(_h2knob, circlePath(CGPointMake(k, k), k));
        CAShapeLayer *in = (CAShapeLayer *)_h2knob.sublayers.firstObject; CGPathRef ip = circlePath(CGPointMake(k, k), k * 0.62);
        in.frame = _h2knob.bounds; in.path = ip; CGPathRelease(ip);
        CGPoint o = [self h2knobOffset];
        _h2knob.position = CGPointMake(_h2origin.x + o.x, _h2origin.y + o.y);
        _h2knob.fillColor = k_on.CGColor;
    }
    [CATransaction commit];
}

// ---- Physical controllers ----
static int32_t axis(float v) { return (int32_t)(fmaxf(-1.f, fminf(1.f, v)) * 32767); }
static void read_pad(GCExtendedGamepad *g) {
    uint64_t m = 0;
    #define K(btn, bit) if (btn.isPressed) m |= 1ull << bit
    K(g.buttonB, B_A); K(g.buttonA, B_B); K(g.buttonY, B_X); K(g.buttonX, B_Y);   // by position: right A, bottom B, top X, left Y
    K(g.leftShoulder, B_L); K(g.rightShoulder, B_R); K(g.leftTrigger, B_ZL); K(g.rightTrigger, B_ZR);
    K(g.buttonMenu, B_PLUS); if (g.buttonOptions) K(g.buttonOptions, B_MINUS);
    if (g.leftThumbstickButton) K(g.leftThumbstickButton, B_LS); if (g.rightThumbstickButton) K(g.rightThumbstickButton, B_RS);
    K(g.dpad.left, B_LEFT); K(g.dpad.up, B_UP); K(g.dpad.right, B_RIGHT); K(g.dpad.down, B_DOWN);
    #undef K
    pthread_mutex_lock(&g_mu);
    g_pad_btn = m; g_pad_lx = axis(g.leftThumbstick.xAxis.value); g_pad_ly = axis(g.leftThumbstick.yAxis.value);
    g_pad_rx = axis(g.rightThumbstick.xAxis.value); g_pad_ry = axis(g.rightThumbstick.yAxis.value);
    pthread_mutex_unlock(&g_mu);
    publish();
}
- (void)padsChanged {
    BOOL any = NO;
    for (GCController *c in GCController.controllers) if (c.extendedGamepad) {
        any = YES; c.extendedGamepad.valueChangedHandler = ^(GCExtendedGamepad *g, GCControllerElement *el) { (void)el; read_pad(g); };
        read_pad(c.extendedGamepad);
    }
    if (!any) { pthread_mutex_lock(&g_mu); g_pad_btn = 0; g_pad_lx = g_pad_ly = g_pad_rx = g_pad_ry = 0; pthread_mutex_unlock(&g_mu); publish(); }
    dispatch_async(dispatch_get_main_queue(), ^{ self->_padOff = any; self->_controls.hidden = any; [self reset]; });
}
@end

UIView *dm_gamepad_view(CGRect frame) { DmGamepad *v = [[DmGamepad alloc] initWithFrame:frame]; g_view = v; return v; }
void dm_gamepad_reset(void) {   // On resign active: release everything (a key held while switching away and released in background gets no "release")
    dispatch_async(dispatch_get_main_queue(), ^{ [g_view reset]; });
    pthread_mutex_lock(&g_mu); g_pad_btn = 0; g_pad_lx = g_pad_ly = g_pad_rx = g_pad_ry = 0; pthread_mutex_unlock(&g_mu); publish();
}
