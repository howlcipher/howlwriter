# Bytecode VM Design Choices in the HowlFrame Transpiler

Designing the HowlFrame language runtime involved balancing compilation speed, runtime debuggability, and target portability. We faced a choice between compiling directly to native machine code via LLVM or compiling to an intermediate representation executed on a custom stack-based bytecode virtual machine.

We chose the bytecode VM architecture for three primary reasons:
1. Deterministic state inspection: Stack frames, local registers, and memory heaps are fully inspectable during execution, enabling time-travel debugging and automated fault isolation.
2. Fast compilation cycles: Generating bytecode instructions is orders of magnitude faster than invoking LLVM optimization passes, providing sub-millisecond feedback loops.
3. Sandboxed execution: Bytecode execution allows strict resource limits on memory allocation and CPU cycles, preventing untrusted scripts from destabilizing the host system.
