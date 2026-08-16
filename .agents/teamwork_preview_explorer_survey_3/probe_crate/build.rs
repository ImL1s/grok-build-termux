fn main() {
    println!("cargo:rerun-if-changed=c_src/test.c");
    cc::Build::new()
        .file("c_src/test.c")
        .compile("test_c");
}
