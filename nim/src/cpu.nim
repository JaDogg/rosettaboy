import std/strformat
import std/bitops

import ram
import consts
import errors

type
    OpArg {.union.} = object
        as_u8: uint8   # B
        as_i8: int8    # b
        as_u16: uint16 # H
    R8 = object
        f: uint8
        a: uint8
        c: uint8
        b: uint8
        e: uint8
        d: uint8
        l: uint8
        h: uint8
    R16 = object
        af: uint16
        bc: uint16
        de: uint16
        hl: uint16
    Regs {.union.} = object
        r8: R8
        r16: R16
    CPU* = object
        ram: ram.RAM
        stop*: bool
        interrupts: bool
        halt: bool
        debug: bool
        cycle: uint32
        owed_cycles: uint32
        regs: Regs
        sp: uint16
        pc: uint16
        flag_z: bool
        flag_n: bool
        flag_c: bool
        flag_h: bool

proc snprintf(buf: cstring, cap: cint, frmt: cstring): cint {.header: "<stdio.h>", importc: "snprintf", varargs.}

const OP_CYCLES = [
    #  1  2  3  4  5  6  7  8  9  A  B  C  D  E  F
    1, 3, 2, 2, 1, 1, 2, 1, 5, 2, 2, 2, 1, 1, 2, 1, # 0
    0, 3, 2, 2, 1, 1, 2, 1, 3, 2, 2, 2, 1, 1, 2, 1, # 1
    2, 3, 2, 2, 1, 1, 2, 1, 2, 2, 2, 2, 1, 1, 2, 1, # 2
    2, 3, 2, 2, 3, 3, 3, 1, 2, 2, 2, 2, 1, 1, 2, 1, # 3
    1, 1, 1, 1, 1, 1, 2, 1, 1, 1, 1, 1, 1, 1, 2, 1, # 4
    1, 1, 1, 1, 1, 1, 2, 1, 1, 1, 1, 1, 1, 1, 2, 1, # 5
    1, 1, 1, 1, 1, 1, 2, 1, 1, 1, 1, 1, 1, 1, 2, 1, # 6
    2, 2, 2, 2, 2, 2, 0, 2, 1, 1, 1, 1, 1, 1, 2, 1, # 7
    1, 1, 1, 1, 1, 1, 2, 1, 1, 1, 1, 1, 1, 1, 2, 1, # 8
    1, 1, 1, 1, 1, 1, 2, 1, 1, 1, 1, 1, 1, 1, 2, 1, # 9
    1, 1, 1, 1, 1, 1, 2, 1, 1, 1, 1, 1, 1, 1, 2, 1, # A
    1, 1, 1, 1, 1, 1, 2, 1, 1, 1, 1, 1, 1, 1, 2, 1, # B
    2, 3, 3, 4, 3, 4, 2, 4, 2, 4, 3, 0, 3, 6, 2, 4, # C
    2, 3, 3, 0, 3, 4, 2, 4, 2, 4, 3, 0, 3, 0, 2, 4, # D
    3, 3, 2, 0, 0, 4, 2, 4, 4, 1, 4, 0, 0, 0, 2, 4, # E
    3, 3, 2, 1, 0, 4, 2, 4, 3, 2, 4, 1, 0, 0, 2, 4, # F
]

const OP_CB_CYCLES = [
    #  1  2  3  4  5  6  7  8  9  A  B  C  D  E  F
    2, 2, 2, 2, 2, 2, 4, 2, 2, 2, 2, 2, 2, 2, 4, 2, # 0
    2, 2, 2, 2, 2, 2, 4, 2, 2, 2, 2, 2, 2, 2, 4, 2, # 1
    2, 2, 2, 2, 2, 2, 4, 2, 2, 2, 2, 2, 2, 2, 4, 2, # 2
    2, 2, 2, 2, 2, 2, 4, 2, 2, 2, 2, 2, 2, 2, 4, 2, # 3
    2, 2, 2, 2, 2, 2, 3, 2, 2, 2, 2, 2, 2, 2, 3, 2, # 4
    2, 2, 2, 2, 2, 2, 3, 2, 2, 2, 2, 2, 2, 2, 3, 2, # 5
    2, 2, 2, 2, 2, 2, 3, 2, 2, 2, 2, 2, 2, 2, 3, 2, # 6
    2, 2, 2, 2, 2, 2, 3, 2, 2, 2, 2, 2, 2, 2, 3, 2, # 7
    2, 2, 2, 2, 2, 2, 4, 2, 2, 2, 2, 2, 2, 2, 4, 2, # 8
    2, 2, 2, 2, 2, 2, 4, 2, 2, 2, 2, 2, 2, 2, 4, 2, # 9
    2, 2, 2, 2, 2, 2, 4, 2, 2, 2, 2, 2, 2, 2, 4, 2, # A
    2, 2, 2, 2, 2, 2, 4, 2, 2, 2, 2, 2, 2, 2, 4, 2, # B
    2, 2, 2, 2, 2, 2, 4, 2, 2, 2, 2, 2, 2, 2, 4, 2, # C
    2, 2, 2, 2, 2, 2, 4, 2, 2, 2, 2, 2, 2, 2, 4, 2, # D
    2, 2, 2, 2, 2, 2, 4, 2, 2, 2, 2, 2, 2, 2, 4, 2, # E
    2, 2, 2, 2, 2, 2, 4, 2, 2, 2, 2, 2, 2, 2, 4, 2, # F
]

const OP_ARG_TYPES = [
    # 1  2  3  4  5  6  7  8  9  A  B  C  D  E  F
    0, 2, 0, 0, 0, 0, 1, 0, 2, 0, 0, 0, 0, 0, 1, 0, # 0
    1, 2, 0, 0, 0, 0, 1, 0, 3, 0, 0, 0, 0, 0, 1, 0, # 1
    3, 2, 0, 0, 0, 0, 1, 0, 3, 0, 0, 0, 0, 0, 1, 0, # 2
    3, 2, 0, 0, 0, 0, 1, 0, 3, 0, 0, 0, 0, 0, 1, 0, # 3
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, # 4
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, # 5
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, # 6
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, # 7
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, # 8
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, # 9
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, # A
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, # B
    0, 0, 2, 2, 2, 0, 1, 0, 0, 0, 2, 0, 2, 2, 1, 0, # C
    0, 0, 2, 0, 2, 0, 1, 0, 0, 0, 2, 0, 2, 0, 1, 0, # D
    1, 0, 0, 0, 0, 0, 1, 0, 3, 0, 2, 0, 0, 0, 1, 0, # E
    1, 0, 0, 0, 0, 0, 1, 0, 3, 0, 2, 0, 0, 0, 1, 0, # F
]

const OP_ARG_BYTES = [0, 1, 2, 1]

const OP_NAMES = [
    "NOP", "LD BC,$%04X", "LD [BC],A", "INC BC", "INC B", "DEC B",
    "LD B,$%02X", "RCLA", "LD [$%04X],SP", "ADD HL,BC", "LD A,[BC]", "DEC BC",
    "INC C", "DEC C", "LD C,$%02X", "RRCA", "STOP", "LD DE,$%04X",
    "LD [DE],A", "INC DE", "INC D", "DEC D", "LD D,$%02X", "RLA",
    "JR %+d", "ADD HL,DE", "LD A,[DE]", "DEC DE", "INC E", "DEC E",
    "LD E,$%02X", "RRA", "JR NZ,%+d", "LD HL,$%04X", "LD [HL+],A", "INC HL",
    "INC H", "DEC H", "LD H,$%02X", "DAA", "JR Z,%+d", "ADD HL,HL",
    "LD A,[HL+]", "DEC HL", "INC L", "DEC L", "LD L,$%02X", "CPL",
    "JR NC,%+d", "LD SP,$%04X", "LD [HL-],A", "INC SP", "INC [HL]", "DEC [HL]",
    "LD [HL],$%02X", "SCF", "JR C,%+d", "ADD HL,SP", "LD A,[HL-]", "DEC SP",
    "INC A", "DEC A", "LD A,$%02X", "CCF", "LD B,B", "LD B,C",
    "LD B,D", "LD B,E", "LD B,H", "LD B,L", "LD B,[HL]", "LD B,A",
    "LD C,B", "LD C,C", "LD C,D", "LD C,E", "LD C,H", "LD C,L",
    "LD C,[HL]", "LD C,A", "LD D,B", "LD D,C", "LD D,D", "LD D,E",
    "LD D,H", "LD D,L", "LD D,[HL]", "LD D,A", "LD E,B", "LD E,C",
    "LD E,D", "LD E,E", "LD E,H", "LD E,L", "LD E,[HL]", "LD E,A",
    "LD H,B", "LD H,C", "LD H,D", "LD H,E", "LD H,H", "LD H,L",
    "LD H,[HL]", "LD H,A", "LD L,B", "LD L,C", "LD L,D", "LD L,E",
    "LD L,H", "LD L,L", "LD L,[HL]", "LD L,A", "LD [HL],B", "LD [HL],C",
    "LD [HL],D", "LD [HL],E", "LD [HL],H", "LD [HL],L", "HALT", "LD [HL],A",
    "LD A,B", "LD A,C", "LD A,D", "LD A,E", "LD A,H", "LD A,L",
    "LD A,[HL]", "LD A,A", "ADD A,B", "ADD A,C", "ADD A,D", "ADD A,E",
    "ADD A,H", "ADD A,L", "ADD A,[HL]", "ADD A,A", "ADC A,B", "ADC A,C",
    "ADC A,D", "ADC A,E", "ADC A,H", "ADC A,L", "ADC A,[HL]", "ADC A,A",
    "SUB A,B", "SUB A,C", "SUB A,D", "SUB A,E", "SUB A,H", "SUB A,L",
    "SUB A,[HL]", "SUB A,A", "SBC A,B", "SBC A,C", "SBC A,D", "SBC A,E",
    "SBC A,H", "SBC A,L", "SBC A,[HL]", "SBC A,A", "AND B", "AND C",
    "AND D", "AND E", "AND H", "AND L", "AND [HL]", "AND A",
    "XOR B", "XOR C", "XOR D", "XOR E", "XOR H", "XOR L",
    "XOR [HL]", "XOR A", "OR B", "OR C", "OR D", "OR E",
    "OR H", "OR L", "OR [HL]", "OR A", "CP B", "CP C",
    "CP D", "CP E", "CP H", "CP L", "CP [HL]", "CP A",
    "RET NZ", "POP BC", "JP NZ,$%04X", "JP $%04X", "CALL NZ,$%04X", "PUSH BC",
    "ADD A,$%02X", "RST 00", "RET Z", "RET", "JP Z,$%04X", "ERR CB",
    "CALL Z,$%04X", "CALL $%04X", "ADC A,$%02X", "RST 08", "RET NC", "POP DE",
    "JP NC,$%04X", "ERR D3", "CALL NC,$%04X", "PUSH DE", "SUB A,$%02X", "RST 10",
    "RET C", "RETI", "JP C,$%04X", "ERR DB", "CALL C,$%04X", "ERR DD",
    "SBC A,$%02X", "RST 18", "LDH [$%02X],A", "POP HL", "LDH [C],A", "DBG",
    "ERR E4", "PUSH HL", "AND $%02X", "RST 20", "ADD SP %+d", "JP HL",
    "LD [$%04X],A", "ERR EB", "ERR EC", "ERR ED", "XOR $%02X", "RST 28",
    "LDH A,[$%02X]", "POP AF", "LDH A,[C]", "DI", "ERR F4", "PUSH AF",
    "OR $%02X", "RST 30", "LD HL,SP%+d", "LD SP,HL", "LD A,[$%04X]", "EI",
    "ERR FC", "ERR FD", "CP $%02X", "RST 38"]

const CB_OP_NAMES = [
    "RLC B", "RLC C", "RLC D", "RLC E", "RLC H", "RLC L", "RLC [HL]", "RLC A",
    "RRC B", "RRC C", "RRC D", "RRC E", "RRC H", "RRC L", "RRC [HL]", "RRC A",
    "RL B", "RL C", "RL D", "RL E", "RL H", "RL L", "RL [HL]", "RL A",
    "RR B", "RR C", "RR D", "RR E", "RR H", "RR L", "RR [HL]", "RR A",
    "SLA B", "SLA C", "SLA D", "SLA E", "SLA H", "SLA L", "SLA [HL]", "SLA A",
    "SRA B", "SRA C", "SRA D", "SRA E", "SRA H", "SRA L", "SRA [HL]", "SRA A",
    "SWAP B", "SWAP C", "SWAP D", "SWAP E", "SWAP H", "SWAP L", "SWAP [HL]", "SWAP A",
    "SRL B", "SRL C", "SRL D", "SRL E", "SRL H", "SRL L", "SRL [HL]", "SRL A",
    "BIT 0,B", "BIT 0,C", "BIT 0,D", "BIT 0,E", "BIT 0,H", "BIT 0,L", "BIT 0,[HL]", "BIT 0,A",
    "BIT 1,B", "BIT 1,C", "BIT 1,D", "BIT 1,E", "BIT 1,H", "BIT 1,L", "BIT 1,[HL]", "BIT 1,A",
    "BIT 2,B", "BIT 2,C", "BIT 2,D", "BIT 2,E", "BIT 2,H", "BIT 2,L", "BIT 2,[HL]", "BIT 2,A",
    "BIT 3,B", "BIT 3,C", "BIT 3,D", "BIT 3,E", "BIT 3,H", "BIT 3,L", "BIT 3,[HL]", "BIT 3,A",
    "BIT 4,B", "BIT 4,C", "BIT 4,D", "BIT 4,E", "BIT 4,H", "BIT 4,L", "BIT 4,[HL]", "BIT 4,A",
    "BIT 5,B", "BIT 5,C", "BIT 5,D", "BIT 5,E", "BIT 5,H", "BIT 5,L", "BIT 5,[HL]", "BIT 5,A",
    "BIT 6,B", "BIT 6,C", "BIT 6,D", "BIT 6,E", "BIT 6,H", "BIT 6,L", "BIT 6,[HL]", "BIT 6,A",
    "BIT 7,B", "BIT 7,C", "BIT 7,D", "BIT 7,E", "BIT 7,H", "BIT 7,L", "BIT 7,[HL]", "BIT 7,A",
    "RES 0,B", "RES 0,C", "RES 0,D", "RES 0,E", "RES 0,H", "RES 0,L", "RES 0,[HL]", "RES 0,A",
    "RES 1,B", "RES 1,C", "RES 1,D", "RES 1,E", "RES 1,H", "RES 1,L", "RES 1,[HL]", "RES 1,A",
    "RES 2,B", "RES 2,C", "RES 2,D", "RES 2,E", "RES 2,H", "RES 2,L", "RES 2,[HL]", "RES 2,A",
    "RES 3,B", "RES 3,C", "RES 3,D", "RES 3,E", "RES 3,H", "RES 3,L", "RES 3,[HL]", "RES 3,A",
    "RES 4,B", "RES 4,C", "RES 4,D", "RES 4,E", "RES 4,H", "RES 4,L", "RES 4,[HL]", "RES 4,A",
    "RES 5,B", "RES 5,C", "RES 5,D", "RES 5,E", "RES 5,H", "RES 5,L", "RES 5,[HL]", "RES 5,A",
    "RES 6,B", "RES 6,C", "RES 6,D", "RES 6,E", "RES 6,H", "RES 6,L", "RES 6,[HL]", "RES 6,A",
    "RES 7,B", "RES 7,C", "RES 7,D", "RES 7,E", "RES 7,H", "RES 7,L", "RES 7,[HL]", "RES 7,A",
    "SET 0,B", "SET 0,C", "SET 0,D", "SET 0,E", "SET 0,H", "SET 0,L", "SET 0,[HL]", "SET 0,A",
    "SET 1,B", "SET 1,C", "SET 1,D", "SET 1,E", "SET 1,H", "SET 1,L", "SET 1,[HL]", "SET 1,A",
    "SET 2,B", "SET 2,C", "SET 2,D", "SET 2,E", "SET 2,H", "SET 2,L", "SET 2,[HL]", "SET 2,A",
    "SET 3,B", "SET 3,C", "SET 3,D", "SET 3,E", "SET 3,H", "SET 3,L", "SET 3,[HL]", "SET 3,A",
    "SET 4,B", "SET 4,C", "SET 4,D", "SET 4,E", "SET 4,H", "SET 4,L", "SET 4,[HL]", "SET 4,A",
    "SET 5,B", "SET 5,C", "SET 5,D", "SET 5,E", "SET 5,H", "SET 5,L", "SET 5,[HL]", "SET 5,A",
    "SET 6,B", "SET 6,C", "SET 6,D", "SET 6,E", "SET 6,H", "SET 6,L", "SET 6,[HL]", "SET 6,A",
    "SET 7,B", "SET 7,C", "SET 7,D", "SET 7,E", "SET 7,H", "SET 7,L", "SET 7,[HL]", "SET 7,A"]

proc create*(ram: ram.RAM, debug: bool): CPU =
    return CPU(
        ram: ram,
        debug: debug
    )

proc interrupt*(cpu: var CPU, interrupt: uint8) =
    cpu.ram.mem_or(consts.Mem_IF, interrupt)
    cpu.halt = false # interrupts interrupt HALT state

proc tick_dma(self: var CPU) =
    # TODO: DMA should take 26 cycles, during which main self.ram is inaccessible
    if self.ram.get(consts.Mem_DMA) != 0:
        let dma_src: uint16 = self.ram.get(consts.Mem_DMA).uint16 shl 8;
        for i in 0..0x9F:
            self.ram.set(consts.Mem_OamBase + i.uint16, self.ram.get(dma_src + i.uint16));
        self.ram.set(consts.Mem_DMA, 0x00)

proc tick_clock(self: var CPU) =
    self.cycle += 1;

    # TODO: writing any value to consts.Mem_DIV should reset it to 0x00
    # increment at 16384Hz (each 64 cycles?)
    if self.cycle mod 64 == 0:
        self.ram.mem_inc(consts.Mem_DIV)

    if bitand(self.ram.get(consts.Mem_TAC), 1 shl 2) == 1 shl 2:
        # timer enable
        let speeds: array[4, int] = [256, 4, 16, 64] # increment per X cycles
        let speed = speeds[bitand(self.ram.get(consts.Mem_TAC), 0x03)]
        if self.cycle mod speed.uint32 == 0:
            if self.ram.get(consts.Mem_TIMA) == 0xFF:
                self.ram.set(consts.Mem_TIMA, self.ram.get(consts.Mem_TMA)) # if timer overflows, load base
                self.interrupt(consts.Interrupt_TIMER)
            self.ram.mem_inc(consts.Mem_TIMA)

proc push(self: var CPU, val: uint16) =
    self.ram.set(self.sp - 1, (bitand((bitand(val, 0xFF00)) shr 8, 0xFF)).uint8)
    self.ram.set(self.sp - 2, (bitand(val, 0xFF)).uint8)
    self.sp -= 2

proc pop(self: var CPU): uint16 =
    let val = bitor(((self.ram.get(self.sp + 1).uint16) shl 8), self.ram.get(self.sp).uint16)
    self.sp += 2
    return val

proc tick_interrupts(self: var CPU) =
    let queued_interrupts = bitand(self.ram.get(consts.Mem_IE), self.ram.get(consts.Mem_IF))
    if self.interrupts and queued_interrupts != 0:
        #tracing::debug!(
        #    "Handling interrupts:::02X &::02X",
        #    self.ram.get(consts.Mem_IE),
        #    self.ram.get(consts.Mem_IF)
        #);

        # no nested interrupts, RETI will re-enable
        self.interrupts = false

        # TODO: wait two cycles
        # TODO: push16(PC) should also take two cycles
        # TODO: one more cycle to store new PC
        if bitand(queued_interrupts, consts.Interrupt_VBLANK) != 0:
            self.push(self.pc);
            self.pc = consts.Mem_VBlankHandler
            self.ram.mem_and(consts.Mem_IF, bitnot(consts.Interrupt_VBLANK))
        elif bitand(queued_interrupts, consts.Interrupt_STAT) != 0:
            self.push(self.pc);
            self.pc = consts.Mem_LcdHandler
            self.ram.mem_and(consts.Mem_IF, bitnot(consts.Interrupt_STAT))
        elif bitand(queued_interrupts, consts.Interrupt_TIMER) != 0:
            self.push(self.pc);
            self.pc = consts.Mem_TimerHandler
            self.ram.mem_and(consts.Mem_IF, bitnot(consts.Interrupt_TIMER))
        elif bitand(queued_interrupts, consts.Interrupt_SERIAL) != 0:
            self.push(self.pc);
            self.pc = consts.Mem_SerialHandler
            self.ram.mem_and(consts.Mem_IF, bitnot(consts.Interrupt_SERIAL))
        elif bitand(queued_interrupts, consts.Interrupt_JOYPAD) != 0:
            self.push(self.pc);
            self.pc = consts.Mem_JoypadHandler
            self.ram.mem_and(consts.Mem_IF, bitnot(consts.Interrupt_JOYPAD))

proc cpu_xor(self: var CPU, val: uint8) =
    self.regs.r8.a = bitxor(self.regs.r8.a, val);

    self.flag_z = self.regs.r8.a == 0;
    self.flag_n = false;
    self.flag_h = false;
    self.flag_c = false;


proc cpu_or(self: var CPU, val: uint8) =
    self.regs.r8.a = bitor(self.regs.r8.a, val);

    self.flag_z = self.regs.r8.a == 0;
    self.flag_n = false;
    self.flag_h = false;
    self.flag_c = false;


proc cpu_and(self: var CPU, val: uint8) =
    self.regs.r8.a = bitand(self.regs.r8.a, val);

    self.flag_z = self.regs.r8.a == 0;
    self.flag_n = false;
    self.flag_h = true;
    self.flag_c = false;


proc cpu_cp(self: var CPU, val: uint8) =
    self.flag_z = self.regs.r8.a == val;
    self.flag_n = true;
    self.flag_h = bitand(self.regs.r8.a, 0x0F) < bitand(val, 0x0F);
    self.flag_c = self.regs.r8.a < val;


proc cpu_add(self: var CPU, val: uint8) =
    self.flag_c = self.regs.r8.a.int32 + val.int32 > 0xFF;
    self.flag_h = bitand(self.regs.r8.a, 0x0F) + bitand(val, 0x0F) > 0x0F;
    self.flag_n = false;
    self.regs.r8.a = (self.regs.r8.a + val);
    self.flag_z = self.regs.r8.a == 0;


proc cpu_adc(self: var CPU, val: uint8) =
    var carry: uint8 = (if self.flag_c: 1 else: 0)
    self.flag_c = (self.regs.r8.a.int32 + val.int32 + carry.int32) > 0xFF;
    self.flag_h = bitand(self.regs.r8.a, 0x0F) + bitand(val, 0x0F) + carry > 0x0F;
    self.flag_n = false;
    self.regs.r8.a = self.regs.r8.a + val + carry;
    self.flag_z = self.regs.r8.a == 0;


proc cpu_sub(self: var CPU, val: uint8) =
    self.flag_c = self.regs.r8.a < val;
    self.flag_h = bitand(self.regs.r8.a, 0x0F) < bitand(val, 0x0F);
    self.regs.r8.a = self.regs.r8.a - val;
    self.flag_z = self.regs.r8.a == 0;
    self.flag_n = true;


proc cpu_sbc(self: var CPU, val: uint8) =
    var carry: uint8 = (if self.flag_c: 1 else: 0)
    var res: int32 = self.regs.r8.a.int32 - val.int32 - carry.int32;
    self.flag_h = bitand(bitxor(self.regs.r8.a, val, res.uint8), (1 shl 4)) != 0;
    self.flag_c = res < 0;
    self.regs.r8.a = self.regs.r8.a - (val + carry);
    self.flag_z = self.regs.r8.a == 0;
    self.flag_n = true;


proc get_reg(self: var CPU, n: uint8): uint8 =
    return case bitand(n, 0x07):
        of 0: self.regs.r8.b
        of 1: self.regs.r8.c
        of 2: self.regs.r8.d
        of 3: self.regs.r8.e
        of 4: self.regs.r8.h
        of 5: self.regs.r8.l
        of 6: self.ram.get(self.regs.r16.hl)
        of 7: self.regs.r8.a
        else: raise errors.InvalidRegister.newException(fmt"Invalid register {n}")


proc set_reg(self: var CPU, n: uint8, val: uint8) =
    case bitand(n, 0x07):
        of 0: self.regs.r8.b = val
        of 1: self.regs.r8.c = val
        of 2: self.regs.r8.d = val
        of 3: self.regs.r8.e = val
        of 4: self.regs.r8.h = val
        of 5: self.regs.r8.l = val
        of 6: self.ram.set(self.regs.r16.hl, val)
        of 7: self.regs.r8.a = val
        else: raise errors.InvalidRegister.newException(fmt"Invalid register {n}")


# FIXME: implement self
#[
Execute a normal instruction (everything except for those
prefixed with 0xCB)
]#
proc tick_main(self: var CPU, op: uint8) =
    # Load args
    var arg: OpArg
    arg.as_u16 = 0xCA75
    var nargs = OP_ARG_BYTES[OP_ARG_TYPES[op]];
    if nargs == 1:
        arg.as_u8 = self.ram.get(self.pc)
        self.pc+=1

    if nargs == 2:
        var arglow = self.ram.get(self.pc).uint16
        self.pc+=1
        var arghigh = self.ram.get(self.pc).uint16
        self.pc+=1
        arg.as_u16 = bitor(arghigh shl 8, arglow)


    # Execute
    var val: uint8 = 0
    var carry: uint8 = 0
    var val16: uint16 = 0

    case op:
        of 0x00: self.stop = self.stop # NOP
        of 0x01: self.regs.r16.bc = arg.as_u16
        of 0x02: self.ram.set(self.regs.r16.bc, self.regs.r8.a)
        of 0x03: self.regs.r16.bc += 1
        of 0x08:
            self.ram.set(arg.as_u16+1, bitand((self.sp shr 8).uint8, 0xFF));
            self.ram.set(arg.as_u16, bitand(self.sp.uint8, 0xFF));
        of 0x0A: self.regs.r8.a = self.ram.get(self.regs.r16.bc)
        of 0x0B: self.regs.r16.bc -= 1

        of 0x10: self.stop = true
        of 0x11: self.regs.r16.de = arg.as_u16
        of 0x12: self.ram.set(self.regs.r16.de, self.regs.r8.a)
        of 0x13: self.regs.r16.de += 1
        of 0x18: self.pc = (self.pc.int32 + arg.as_i8.int32).uint16
        of 0x1A: self.regs.r8.a = self.ram.get(self.regs.r16.de)
        of 0x1B: self.regs.r16.de -= 1

        of 0x20:
            if not self.flag_z:
                self.pc = (self.pc.int32 + arg.as_i8.int32).uint16
        of 0x21: self.regs.r16.hl = arg.as_u16
        of 0x22:
            self.ram.set(self.regs.r16.hl, self.regs.r8.a);
            self.regs.r16.hl+=1
        of 0x23: self.regs.r16.hl += 1
        of 0x27:
            val16 = self.regs.r8.a;
            if not self.flag_n:
                if self.flag_h or bitand(val16, 0x0F) > 9:
                    val16 += 6;
                if self.flag_c or val16 > 0x9F:
                    val16 += 0x60;

            else:
                if self.flag_h:
                    val16 -= 6;
                    if not self.flag_c:
                        val16 = bitand(val16, 0xFF)

                if self.flag_c:
                    val16 -= 0x60;

            self.flag_h = false;
            if bitand(val16, 0x100) != 0:
                self.flag_c = true;
            self.regs.r8.a = val16.uint8
            self.flag_z = self.regs.r8.a == 0;
        of 0x28:
            if self.flag_z:
                self.pc = (self.pc.int32 + arg.as_i8.int32).uint16
        of 0x2A:
            self.regs.r8.a = self.ram.get(self.regs.r16.hl)
            self.regs.r16.hl+=1
        of 0x2B:
            self.regs.r16.hl-=1;
        of 0x2F:
            self.regs.r8.a = bitxor(self.regs.r8.a, 0xFF)
            self.flag_n = true;
            self.flag_h = true;

        of 0x30:
            if not self.flag_c:
                self.pc = (self.pc.int32 + arg.as_i8.int32).uint16
        of 0x31:
            self.sp = arg.as_u16;
        of 0x32:
            self.ram.set(self.regs.r16.hl, self.regs.r8.a);
            self.regs.r16.hl-=1
        of 0x33:
            self.sp += 1
        of 0x37:
            self.flag_n = false; self.flag_h = false; self.flag_c = true;
        of 0x38:
            if self.flag_c:
                self.pc = (self.pc.int32 + arg.as_i8.int32).uint16
        of 0x3A:
            self.regs.r8.a = self.ram.get(self.regs.r16.hl);
            self.regs.r16.hl -= 1
        of 0x3B:
            self.sp -= 1
        of 0x3F:
            self.flag_c = not self.flag_c;
            self.flag_n = false;
            self.flag_h = false;

        # INC r
        of 0x04, 0x0C, 0x14, 0x1C, 0x24, 0x2C, 0x34, 0x3C:
            val = self.get_reg((op-0x04) shr 3);
            self.flag_h = bitand(val, 0x0F) == 0x0F;
            val+=1;
            self.flag_z = val == 0;
            self.flag_n = false;
            self.set_reg((op-0x04) shr 3, val);

        # DEC r
        of 0x05, 0x0D, 0x15, 0x1D, 0x25, 0x2D, 0x35, 0x3D:
            val = self.get_reg((op-0x05) shr 3);
            val-=1;
            self.flag_h = bitand(val, 0x0F) == 0x0F;
            self.flag_z = val == 0;
            self.flag_n = true;
            self.set_reg((op-0x05) shr 3, val);

        # LD r,n
        of 0x06, 0x0E, 0x16, 0x1E, 0x26, 0x2E, 0x36, 0x3E:
            self.set_reg((op-0x06) shr 3, arg.as_u8);

        # RCLA, RLA, RRCA, RRA
        of 0x07, 0x17, 0x0F, 0x1F:
            carry = if self.flag_c: 1 else: 0
            if(op == 0x07): # RCLA
                self.flag_c = bitand(self.regs.r8.a, (1 shl 7)) != 0;
                self.regs.r8.a = bitor((self.regs.r8.a shl 1), (self.regs.r8.a shr 7));

            if(op == 0x17): # RLA
                self.flag_c = bitand(self.regs.r8.a, (1 shl 7)) != 0;
                self.regs.r8.a = bitor((self.regs.r8.a shl 1), carry);

            if(op == 0x0F): # RRCA
                self.flag_c = bitand(self.regs.r8.a, (1 shl 0)) != 0;
                self.regs.r8.a = bitor((self.regs.r8.a shr 1), (self.regs.r8.a shl 7));

            if(op == 0x1F): # RRA
                self.flag_c = bitand(self.regs.r8.a, (1 shl 0)) != 0;
                self.regs.r8.a = bitor((self.regs.r8.a shr 1), (carry shl 7));

            self.flag_n = false;
            self.flag_h = false;
            self.flag_z = false;

        # ADD HL,rr
        of 0x09, 0x19, 0x29, 0x39:
            if(op == 0x09):
                val16 = self.regs.r16.bc;
            if(op == 0x19):
                val16 = self.regs.r16.de;
            if(op == 0x29):
                val16 = self.regs.r16.hl;
            if(op == 0x39):
                val16 = self.sp;
            self.flag_h = (bitand(self.regs.r16.hl, 0x0FFF) + bitand(val16, 0x0FFF) > 0x0FFF);
            self.flag_c = (self.regs.r16.hl.int32 + val16.int32 > 0xFFFF);
            self.regs.r16.hl += val16;
            self.flag_n = false;

        of 0x40 .. 0x7F: # LD r,r
            if(op == 0x76):
                # FIXME: weird timing side effects
                self.halt = true;
            else:
                self.set_reg((op - 0x40) shr 3, self.get_reg(op - 0x40));

        of 0x80 .. 0x87: self.cpu_add(self.get_reg(op))
        of 0x88 .. 0x8F: self.cpu_adc(self.get_reg(op))
        of 0x90 .. 0x97: self.cpu_sub(self.get_reg(op))
        of 0x98 .. 0x9F: self.cpu_sbc(self.get_reg(op))
        of 0xA0 .. 0xA7: self.cpu_and(self.get_reg(op))
        of 0xA8 .. 0xAF: self.cpu_xor(self.get_reg(op))
        of 0xB0 .. 0xB7: self.cpu_or(self.get_reg(op))
        of 0xB8 .. 0xBF: self.cpu_cp(self.get_reg(op))

        of 0xC0:
            if not self.flag_z:
                self.pc = self.pop();
        of 0xC1:
            self.regs.r16.bc = self.pop();
        of 0xC2:
            if not self.flag_z:
                self.pc = arg.as_u16;
        of 0xC3:
            self.pc = arg.as_u16;
        of 0xC4:
            if not self.flag_z:
                self.push(self.pc);
                self.pc = arg.as_u16;
        of 0xC5:
            self.push(self.regs.r16.bc);
        of 0xC6:
            self.cpu_add(arg.as_u8);
        of 0xC7:
            self.push(self.pc); self.pc = 0x00;
        of 0xC8:
            if(self.flag_z):
                self.pc = self.pop();
        of 0xC9:
            self.pc = self.pop();
        of 0xCA:
            if(self.flag_z):
                self.pc = arg.as_u16;
        # of 0xCB: break;
        of 0xCC:
            if(self.flag_z):
                self.push(self.pc);
                self.pc = arg.as_u16;
        of 0xCD:
            self.push(self.pc);
            self.pc = arg.as_u16;
        of 0xCE:
            self.cpu_adc(arg.as_u8);
        of 0xCF:
            self.push(self.pc);
            self.pc = 0x08;

        of 0xD0:
            if not self.flag_c:
                self.pc = self.pop();
        of 0xD1:
            self.regs.r16.de = self.pop();
        of 0xD2:
            if not self.flag_c:
                self.pc = arg.as_u16;
        # of 0xD3: break;
        of 0xD4:
            if not self.flag_c:
                self.push(self.pc);
                self.pc = arg.as_u16;
        of 0xD5:
            self.push(self.regs.r16.de);
        of 0xD6:
            self.cpu_sub(arg.as_u8);
        of 0xD7:
            self.push(self.pc); self.pc = 0x10;
        of 0xD8:
            if(self.flag_c):
                self.pc = self.pop();
        of 0xD9:
            self.pc = self.pop();
            self.interrupts = true;
        of 0xDA:
            if(self.flag_c):
                self.pc = arg.as_u16;
        # of 0xDB: break;
        of 0xDC:
            if(self.flag_c):
                self.push(self.pc);
                self.pc = arg.as_u16;
        # of 0xDD: break;
        of 0xDE:
            self.cpu_sbc(arg.as_u8);
        of 0xDF:
            self.push(self.pc); self.pc = 0x18;

        of 0xE0:
            self.ram.set(0xFF00 + arg.as_u8.uint16, self.regs.r8.a);
            if(arg.as_u8 == 0x01):
                write(stdout, self.regs.r8.a.char)
        of 0xE1:
            self.regs.r16.hl = self.pop();
        of 0xE2:
            self.ram.set(0xFF00 + self.regs.r8.c.uint16, self.regs.r8.a);
            if(self.regs.r8.c == 0x01):
                write(stdout, self.regs.r8.a.char)
        # of 0xE3: break;
        # of 0xE4: break;
        of 0xE5:
            self.push(self.regs.r16.hl);
        of 0xE6:
            self.cpu_and(arg.as_u8);
        of 0xE7:
            self.push(self.pc); self.pc = 0x20;
        of 0xE8:
            val16 = (self.sp.int + arg.as_i8.int).uint16
            # self.flag_h = ((self.sp & 0x0FFF) + (arg.as_i8 & 0x0FFF) > 0x0FFF);
            # self.flag_c = (self.sp + arg.as_i8 > 0xFFFF);
            self.flag_h = bitand(bitxor(self.sp, arg.as_i8.uint16, val16), 0x10) > 0;
            self.flag_c = bitand(bitxor(self.sp, arg.as_i8.uint16, val16), 0x100) > 0;
            self.sp = (self.sp.int + arg.as_i8.int).uint16;
            self.flag_z = false;
            self.flag_n = false;
        of 0xE9:
            self.pc = self.regs.r16.hl;
        of 0xEA:
            self.ram.set(arg.as_u16, self.regs.r8.a);
        # of 0xEB: break;
        # of 0xEC: break;
        # of 0xED: break;
        of 0xEE:
            self.cpu_xor(arg.as_u8);
        of 0xEF:
            self.push(self.pc); self.pc = 0x28;

        of 0xF0:
            self.regs.r8.a = self.ram.get(0xFF00 + arg.as_u8.uint16);
        of 0xF1:
            self.regs.r16.af = bitand(self.pop(), 0xFFF0);
            self.flag_z = bitand(self.regs.r8.f, 1 shl 7) != 0;
            self.flag_n = bitand(self.regs.r8.f, 1 shl 6) != 0;
            self.flag_h = bitand(self.regs.r8.f, 1 shl 5) != 0;
            self.flag_c = bitand(self.regs.r8.f, 1 shl 4) != 0;
        of 0xF2:
            self.regs.r8.a = self.ram.get(0xFF00 + self.regs.r8.c.uint16);
        of 0xF3:
            self.interrupts = false;
        # of 0xF4: break;
        of 0xF5:
            self.push(self.regs.r16.af);
        of 0xF6:
            self.cpu_or(arg.as_u8);
        of 0xF7:
            self.push(self.pc); self.pc = 0x30;
        of 0xF8:
            if(arg.as_i8 >= 0):
                self.flag_c = (bitand(self.sp, 0xFF) + bitand(arg.as_i8.uint16, 0xFF)) > 0xFF;
                self.flag_h = (bitand(self.sp, 0x0F) + bitand(arg.as_i8.uint16, 0x0F)) > 0x0F;
            else:
                self.flag_c = bitand((self.sp + arg.as_i8.uint16), 0xFF) <= bitand(self.sp, 0xFF);
                self.flag_h = bitand((self.sp + arg.as_i8.uint16), 0x0F) <= bitand(self.sp, 0x0F);

            # self.flag_h = ((((self.sp & 0x0f) + (arg.as_u8 & 0x0f)) & 0x10) != 0);
            # self.flag_c = ((((self.sp & 0xff) + (arg.as_u8 & 0xff)) & 0x100) != 0);
            self.regs.r16.hl = (self.sp.int + arg.as_i8.int).uint16;
            self.flag_z = false;
            self.flag_n = false;
        of 0xF9:
            self.sp = self.regs.r16.hl;
        of 0xFA:
            self.regs.r8.a = self.ram.get(arg.as_u16);
        of 0xFB:
            self.interrupts = true;
        of 0xFC:
            raise errors.UnitTestPassed.newException("Unit test passed"); # unofficial
        of 0xFD:
            raise errors.UnitTestFailed.newException("Unit test failed"); # unofficial
        of 0xFE:
            self.cpu_cp(arg.as_u8);
        of 0xFF:
            self.push(self.pc);
            self.pc = 0x38;

        # missing ops
        else:
            raise errors.InvalidOpcode.newException(fmt"Invalid opcode: {op}");


#[
 * CB instructions all share a format where the first
 * 5 bits of the opcode defines the instruction, and
 * the latter 3 bits of the opcode define the data to
 * work with (7 registers + 1 "RAM at HL").
 *
 * We can take advantage of self to avoid copy-pasting,
 * by loading the data based on the 3 bits, executing
 * an instruction based on the 5, and then storing the
 * data based on the 3 again.
]#
proc tick_cb(self: var CPU, op: uint8) =
    var val: uint8
    var orig_c: bool
    var bit: uint8

    val = self.get_reg(op);
    case bitand(op, 0xF8):
        # RLC
        of 0x00 .. 0x07:
            self.flag_c = bitand(val, (1 shl 7)) != 0;
            val = val shl 1
            if(self.flag_c):
                val = bitor(val, 1 shl 0);
            self.flag_n = false;
            self.flag_h = false;
            self.flag_z = val == 0;

        # RRC
        of 0x08 .. 0x0F:
            self.flag_c = bitand(val, (1 shl 0)) != 0;
            val = val shr 1
            if(self.flag_c):
                val = bitor(val, 1 shl 7);
            self.flag_n = false;
            self.flag_h = false;
            self.flag_z = val == 0;

        # RL
        of 0x10 .. 0x17:
            orig_c = self.flag_c;
            self.flag_c = bitand(val, (1 shl 7)) != 0;
            val = val shl 1
            if(orig_c):
                val = bitor(val, 1 shl 0);
            self.flag_n = false;
            self.flag_h = false;
            self.flag_z = val == 0;

        # RR
        of 0x18 .. 0x1F:
            orig_c = self.flag_c;
            self.flag_c = bitand(val, (1 shl 0)) != 0;
            val = val shr 1
            if(orig_c):
                val = bitor(val, 1 shl 7);
            self.flag_n = false;
            self.flag_h = false;
            self.flag_z = val == 0;

        # SLA
        of 0x20 .. 0x27:
            self.flag_c = bitand(val, (1 shl 7)) != 0;
            val = val shl 1
            val = bitand(val, 0xFF)
            self.flag_n = false;
            self.flag_h = false;
            self.flag_z = val == 0;

        # SRA
        of 0x28 .. 0x2F:
            self.flag_c = bitand(val, (1 shl 0)) != 0;
            val = val shr 1
            if bitand(val, (1 shl 6)) != 0:
                val = bitor(val, 1 shl 7);
            self.flag_n = false;
            self.flag_h = false;
            self.flag_z = val == 0;

        # SWAP
        of 0x30 .. 0x37:
            val = bitor((bitand(val, 0xF0) shr 4), (bitand(val, 0x0F) shl 4))
            self.flag_c = false;
            self.flag_n = false;
            self.flag_h = false;
            self.flag_z = val == 0;

        # SRL
        of 0x38 .. 0x3F:
            self.flag_c = bitand(val, (1 shl 0)) != 0;
            val = val shr 1
            self.flag_n = false;
            self.flag_h = false;
            self.flag_z = val == 0;

        # BIT
        of 0x40 .. 0x7F:
            bit = bitand(op, 0b00111000) shr 3;
            self.flag_z = bitand(val, (1 shl bit).uint8) == 0;
            self.flag_n = false;
            self.flag_h = true;

        # RES
        of 0x80 .. 0xBF:
            bit = bitand(op, 0b00111000) shr 3;
            val = bitand(val, bitxor((1 shl bit).uint8, 0xFF));

        # SET
        of 0xC0 .. 0xFF:
            bit = bitand(op, 0b00111000) shr 3;
            val = bitor(val, (1 shl bit).uint8);

    self.set_reg(op, val);


proc dump_regs(self: var CPU) =
    let IE = self.ram.get(consts.Mem_IE);
    let IF = self.ram.get(consts.Mem_IF);
    let z = bitxor('z'.uint8, bitand((self.regs.r8.f shr 7), 1) shl 5).char;
    let n = bitxor('n'.uint8, bitand((self.regs.r8.f shr 6), 1) shl 5).char;
    let h = bitxor('h'.uint8, bitand((self.regs.r8.f shr 5), 1) shl 5).char;
    let c = bitxor('c'.uint8, bitand((self.regs.r8.f shr 4), 1) shl 5).char;
    let v = if bitand(IE shr 0, 1) == 1: bitxor('v'.uint8, bitand((IF shr 0), 1) shl 5).char else: '_'
    let l = if bitand(IE shr 1, 1) == 1: bitxor('l'.uint8, bitand((IF shr 1), 1) shl 5).char else: '_'
    let t = if bitand(IE shr 2, 1) == 1: bitxor('t'.uint8, bitand((IF shr 2), 1) shl 5).char else: '_'
    let s = if bitand(IE shr 3, 1) == 1: bitxor('s'.uint8, bitand((IF shr 3), 1) shl 5).char else: '_'
    let j = if bitand(IE shr 4, 1) == 1: bitxor('j'.uint8, bitand((IF shr 4), 1) shl 5).char else: '_'
    var op = self.ram.get(self.pc);
    var op_str = newString(1024)
    if op == 0xCB:
        op = self.ram.get(self.pc + 1)
        op_str = CB_OP_NAMES[op]
    else:
        if(OP_ARG_TYPES[op] == 0):
            op_str = OP_NAMES[op]
        if(OP_ARG_TYPES[op] == 1):
            let arg = self.ram.get(self.pc + 1)
            op_str.setLen snprintf(op_str.cstring, 1024, OP_NAMES[op].cstring, arg)
        if(OP_ARG_TYPES[op] == 2):
            let arg = bitor(self.ram.get(self.pc + 2).uint16 shl 8, self.ram.get(self.pc + 1))
            op_str.setLen snprintf(op_str.cstring, 1024, OP_NAMES[op].cstring, arg)
        if(OP_ARG_TYPES[op] == 3):
            var arg = self.ram.get(self.pc + 1).int16
            if arg > 127:
                arg -= 256
            op_str.setLen snprintf(op_str.cstring, 1024, OP_NAMES[op].cstring, arg)
    # if(cycle % 10 == 0)
    # printf("A F  B C  D E  H L  : SP   = [SP] : F    : IE/IF : PC   = OP : INSTR\n");
    var line = ""
    line.add(fmt"{self.regs.r16.af:04X} {self.regs.r16.bc:04X} {self.regs.r16.de:04X} {self.regs.r16.hl:04X} : ")
    line.add(fmt"{self.sp:04X} = {self.ram.get(self.sp + 1):02X}{self.ram.get(self.sp):02X} : ")
    line.add(fmt"{z}{n}{h}{c} : {v}{l}{t}{s}{j} : {self.pc:04X} = {op:02X} : {op_str}")
    echo line

#[
Pick an instruction from RAM as pointed to by the
Program Counter register; if the instruction takes
an argument then pick that too; then execute it.
]#
proc tick_instructions(self: var CPU) =
    # if the previous instruction was large, let's not run any
    # more instructions until other subsystems have caught up
    if self.owed_cycles > 0:
        self.owed_cycles -= 1
        return

    if self.debug:
        self.dump_regs();

    var op = self.ram.get(self.pc)
    self.pc += 1
    if op == 0xCB:
        op = self.ram.get(self.pc)
        self.pc+=1
        self.tick_cb(op);
        self.owed_cycles = OP_CB_CYCLES[op].uint32;
    else:
        self.tick_main(op);
        self.owed_cycles = OP_CYCLES[op].uint32;

    # Flags should be union'ed with the F register, but nim doesn't
    # support that, so let's manually sync from flags to register
    # after every instruction...
    self.regs.r8.f = bitor(
        0,
        if self.flag_z: 1 shl 7 else: 0,
        if self.flag_n: 1 shl 6 else: 0,
        if self.flag_h: 1 shl 5 else: 0,
        if self.flag_c: 1 shl 4 else: 0
    ).uint8

    # HALT has cycles=0
    if self.owed_cycles > 0:
        self.owed_cycles -= 1


proc tick*(self: var CPU) =
    self.tick_dma()
    self.tick_clock()
    self.tick_interrupts()
    if self.halt:
        return
    if self.stop:
        return
    self.tick_instructions()

