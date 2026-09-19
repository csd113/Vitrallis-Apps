//! Require the `PocketCHIP` X11 compositor used by the platform rendering contract.
#[cfg(target_os = "linux")]
use anyhow::{Result, ensure};

#[cfg(target_os = "linux")]
struct XLibrary(*mut libc::c_void);
#[cfg(target_os = "linux")]
impl Drop for XLibrary {
    fn drop(&mut self) {
        // SAFETY: this handle came from a successful dlopen and is closed once.
        unsafe {
            libc::dlclose(self.0);
        }
    }
}

#[cfg(target_os = "linux")]
pub fn present(window: &sdl2::video::Window) -> Result<bool> {
    // SAFETY: zero is a valid unknown SDL subsystem and null union storage. SDL
    // initializes it before the selected X11 union member is accessed below.
    let mut info: sdl2::sys::SDL_SysWMinfo = unsafe { std::mem::zeroed() };
    info.version = sdl2::sys::SDL_version {
        major: 2,
        minor: 0,
        patch: 0,
    };
    // SAFETY: live SDL window and writable, versioned WM-info structure.
    ensure!(
        unsafe { sdl2::sys::SDL_GetWindowWMInfo(window.raw(), &raw mut info) }
            == sdl2::sys::SDL_bool::SDL_TRUE,
        "Cannot inspect X11 presentation"
    );
    if info.subsystem != sdl2::sys::SDL_SYSWM_TYPE::SDL_SYSWM_X11 {
        return Ok(true);
    }
    // SAFETY: SDL identified the active member as X11; the display is SDL-owned.
    let display = unsafe { info.info.x11.display }.cast::<libc::c_void>();
    ensure!(!display.is_null(), "Missing X11 display");
    // SAFETY: fixed system library name, no user paths or executable data.
    let handle =
        unsafe { libc::dlopen(c"libX11.so.6".as_ptr(), libc::RTLD_NOW | libc::RTLD_LOCAL) };
    ensure!(
        !handle.is_null(),
        "Cannot inspect the platform X11 compositor"
    );
    let library = XLibrary(handle);
    // SAFETY: symbol names are fixed Xlib ABI exports; the library stays live.
    let (intern, owner, screen) = unsafe {
        (
            libc::dlsym(library.0, c"XInternAtom".as_ptr()),
            libc::dlsym(library.0, c"XGetSelectionOwner".as_ptr()),
            libc::dlsym(library.0, c"XDefaultScreen".as_ptr()),
        )
    };
    ensure!(
        !intern.is_null() && !owner.is_null() && !screen.is_null(),
        "Missing Xlib compositor query symbols"
    );
    // SAFETY: exact public Xlib function signatures, resolved above.
    let intern: unsafe extern "C" fn(
        *mut libc::c_void,
        *const libc::c_char,
        libc::c_int,
    ) -> libc::c_ulong = unsafe { std::mem::transmute(intern) };
    // SAFETY: exact public Xlib function signature.
    let owner: unsafe extern "C" fn(*mut libc::c_void, libc::c_ulong) -> libc::c_ulong =
        unsafe { std::mem::transmute(owner) };
    // SAFETY: exact public Xlib function signature.
    let screen: unsafe extern "C" fn(*mut libc::c_void) -> libc::c_int =
        unsafe { std::mem::transmute(screen) };
    // SAFETY: display is live on the SDL UI thread, never accessed concurrently.
    let screen = unsafe { screen(display) };
    let name = std::ffi::CString::new(format!("_NET_WM_CM_S{screen}"))?;
    // SAFETY: valid display, NUL-terminated selection name; only-if-exists=true.
    let atom = unsafe { intern(display, name.as_ptr(), 1) };
    // SAFETY: valid display and existing atom; no mutation or ownership change.
    Ok(atom != 0 && unsafe { owner(display, atom) } != 0)
}
