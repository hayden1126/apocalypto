//! The single FFI crossing for the apocalypto core (spec section 4.1).
//! Two lanes by design, never merged: the low-rate control/UI lane
//! (flutter_rust_bridge, deferred until a Dart toolchain exists) and the
//! 100 Hz sensor lane (`capi`, a direct C ABI that bypasses Dart).
//! Everything crossing here is flat owned data: no lifetimes, no crypto types.
#![deny(unsafe_op_in_unsafe_fn)]

pub mod capi;
pub mod dto;
