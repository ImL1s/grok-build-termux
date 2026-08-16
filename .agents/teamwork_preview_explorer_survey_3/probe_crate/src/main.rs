extern "C" {
    fn test_func();
}

fn main() {
    println!("Hello from Rust!");
    unsafe { test_func(); }
}
