from enum import Enum
from typing import Optional
import sys
from textwrap import dedent

from .errors import UnitTestPassed, UnitTestFailed
from .ram import RAM
from .consts import *


class Reg(Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"
    F = "F"
    H = "H"
    L = "L"

    BC = "BC"
    DE = "DE"
    AF = "AF"
    HL = "HL"

    SP = "SP"
    PC = "PC"

    MEM_AT_HL = "MEM_AT_HL"


GEN_REGS = ["B", "C", "D", "E", "H", "L", "[HL]", "A"]


class OpNotImplemented(Exception):
    pass


def opcode(name: str, cycles: int, args: str = ""):
    def dec(fn):
        fn.name = name
        fn.cycles = cycles
        fn.args = args
        return fn

    return dec


class CPU:
    # <editor-fold description="Init">
    def __init__(self, ram: RAM, debug=False) -> None:
        self.ram = ram
        self.interrupts = True
        self.halt = False
        self.stop = False
        self.cycle = 0
        self._nopslide = 0
        self._debug = debug
        self._debug_str = ""
        self._owed_cycles = 0

        # registers
        # boot rom should set these to defaults
        self.A = 0  # 0x01  # GB / SGB. FF=GBP, 11=GBC
        self.B = 0  # 0x00
        self.C = 0  # 0x13
        self.D = 0  # 0x00
        self.E = 0  # 0xD8
        self.H = 0  # 0x01
        self.L = 0  # 0x4D

        self.SP = 0x0000  # 0xFFFE
        self.PC = 0x0000

        # flags
        # should be set by boot rom
        self.FLAG_Z: bool = False  # True   # zero
        self.FLAG_N: bool = False  # False  # subtract
        self.FLAG_H: bool = False  # True   # half-carry
        self.FLAG_C: bool = False  # True   # carry

        self.ops = [getattr(self, "op%02X" % n) for n in range(0x00, 0xFF + 1)]
        self.cb_ops = [getattr(self, "opCB%02X" % n) for n in range(0x00, 0xFF + 1)]

    def dump(self, pc: int, cmd_str: str) -> str:
        ien = self.ram[Mem.IE]
        ifl = self.ram[Mem.IF]

        def flag(i: int, c: str) -> str:
            if ien & i != 0:
                if ifl & i != 0:
                    return c.upper()
                else:
                    return c
            else:
                return "_"

        v = flag(Interrupt.VBLANK, "v")
        l = flag(Interrupt.STAT, "l")
        t = flag(Interrupt.TIMER, "t")
        s = flag(Interrupt.SERIAL, "s")
        j = flag(Interrupt.JOYPAD, "j")

        op = self.ram[pc + 1] if self.ram[pc] == 0xCB else self.ram[pc]

        return "{:04X} {:04X} {:04X} {:04X} : {:04X} = {:02X}{:02X} : {}{}{}{} : {}{}{}{}{} : {:04X} = {:02X} : {}".format(
            self.AF,
            self.BC,
            self.DE,
            self.HL,
            self.SP,
            self.ram[(self.SP + 1) & 0xFFFF],
            self.ram[self.SP],
            "Z" if self.FLAG_Z else "z",
            "N" if self.FLAG_N else "n",
            "H" if self.FLAG_H else "h",
            "C" if self.FLAG_C else "c",
            v,
            l,
            t,
            s,
            j,
            pc,
            op,
            cmd_str,
        )

    def interrupt(self, i: int) -> None:
        """
        Set a given interrupt bit - on the next tick, if the interrupt
        handler for this interrupt is enabled (and interrupts in general
        are enabled), then the interrupt handler will be called.
        """
        self.ram[Mem.IF] |= i
        self.halt = False  # interrupts interrupt HALT state

    def tick(self) -> None:
        self.tick_dma()
        self.tick_clock()
        self.tick_interrupts()
        if self.halt:
            return
        if self.stop:
            return
        self.tick_instructions()

    def tick_dma(self) -> None:
        """
        If there is a non-zero value in ram[Mem.DMA], eg 0x42, then
        we should copy memory from eg 0x4200 to OAM space.
        """
        # TODO: DMA should take 26 cycles, during which main RAM is inaccessible
        if self.ram[Mem.DMA]:
            dma_src = self.ram[Mem.DMA] << 8
            for i in range(0, 0xA0):
                self.ram[Mem.OAM_BASE + i] = self.ram[dma_src + i]
            self.ram[Mem.DMA] = 0x00

    def tick_clock(self) -> None:
        """
        Increment the timer registers, and send an interrupt
        when `ram[Mem.:TIMA]` wraps around.
        """
        self.cycle += 1

        # TODO: writing any value to Mem.:DIV should reset it to 0x00
        # increment at 16384Hz (each 64 cycles?)
        if self.cycle % 64 == 0:
            self.ram[Mem.DIV] = (self.ram[Mem.DIV] + 1) & 0xFF

        if self.ram[Mem.TAC] & 1 << 2 == 1 << 2:
            # timer enable
            speeds = [256, 4, 16, 64]  # increment per X cycles
            speed = speeds[self.ram[Mem.TAC] & 0x03]
            if self.cycle % speed == 0:
                if self.ram[Mem.TIMA] == 0xFF:
                    self.ram[Mem.TIMA] = self.ram[
                        Mem.TMA
                    ]  # if timer overflows, load base
                    self.interrupt(Interrupt.TIMER)
                self.ram[Mem.TIMA] += 1

    def tick_interrupts(self) -> None:
        """
        Compare Interrupt Enabled and Interrupt Flag registers - if
        there are any interrupts which are both enabled and flagged,
        clear the flag and call the handler for the first of them.
        """
        queued_interrupts = self.ram[Mem.IE] & self.ram[Mem.IF]
        if self.interrupts and queued_interrupts:
            if self._debug:
                print(
                    f"Handling interrupts: {self.ram[Mem.IE]:02X} & {self.ram[Mem.IF]:02X}"
                )

            # no nested interrupts, RETI will re-enable
            self.interrupts = False

            # TODO: wait two cycles
            # TODO: push16(PC) should also take two cycles
            # TODO: one more cycle to store new PC
            if queued_interrupts & Interrupt.VBLANK:
                self._push16(Reg.PC)
                self.PC = Mem.VBLANK_HANDLER
                self.ram[Mem.IF] &= ~Interrupt.VBLANK
            elif queued_interrupts & Interrupt.STAT:
                self._push16(Reg.PC)
                self.PC = Mem.LCD_HANDLER
                self.ram[Mem.IF] &= ~Interrupt.STAT
            elif queued_interrupts & Interrupt.TIMER:
                self._push16(Reg.PC)
                self.PC = Mem.TIMER_HANDLER
                self.ram[Mem.IF] &= ~Interrupt.TIMER
            elif queued_interrupts & Interrupt.SERIAL:
                self._push16(Reg.PC)
                self.PC = Mem.SERIAL_HANDLER
                self.ram[Mem.IF] &= ~Interrupt.SERIAL
            elif queued_interrupts & Interrupt.JOYPAD:
                self._push16(Reg.PC)
                self.PC = Mem.JOYPAD_HANDLER
                self.ram[Mem.IF] &= ~Interrupt.JOYPAD

    def tick_instructions(self) -> None:
        # TODO: extra cycles when conditional jumps are taken
        if self._owed_cycles:
            self._owed_cycles -= 4
            return

        src = self.ram

        original_pc = self.PC

        ins = src[self.PC]
        if ins == 0xCB:
            ins = src[self.PC + 1]
            cmd = self.cb_ops[ins]
            self.PC += 1
        else:
            cmd = self.ops[ins]

        param: Optional[int]

        if cmd.args == "B":
            param = src[self.PC + 1]
            cmd_str = cmd.name.replace("n", "$%02X" % param)
            self.PC += 2
        elif cmd.args == "b":
            param = src[self.PC + 1]
            if param > 128:
                param -= 256
                cmd_str = cmd.name.replace("n", "%d" % param)
            else:
                cmd_str = cmd.name.replace("n", "+%d" % param)
            self.PC += 2
        elif cmd.args == "H":
            param = (src[self.PC + 1]) | (src[self.PC + 2] << 8)
            cmd_str = cmd.name.replace("nn", "$%04X" % param)
            self.PC += 3
        else:
            param = None
            cmd_str = cmd.name
            self.PC += 1
        self._debug_str = f"[{self.PC:04X}({ins:02X})]: {cmd_str}"

        if self._debug:
            print(self.dump(original_pc, cmd_str))

        if param is not None:
            cmd(param)
        else:
            cmd()

        self._owed_cycles = cmd.cycles - 4

    # </editor-fold>

    # <editor-fold description="Registers">
    @property
    def AF(self) -> int:
        """
        >>> cpu = CPU()
        >>> cpu.A = 0x01
        >>> cpu.FLAG_Z = True
        >>> cpu.FLAG_N = True
        >>> cpu.FLAG_H = True
        >>> cpu.FLAG_C = True
        >>> cpu.AF
        496
        """
        return (
            self.A << 8
            | (self.FLAG_Z or 0) << 7
            | (self.FLAG_N or 0) << 6
            | (self.FLAG_H or 0) << 5
            | (self.FLAG_C or 0) << 4
        )

    @AF.setter
    def AF(self, val: int) -> None:
        self.A = val >> 8 & 0xFF
        self.FLAG_Z = bool(val & 0b10000000)
        self.FLAG_N = bool(val & 0b01000000)
        self.FLAG_H = bool(val & 0b00100000)
        self.FLAG_C = bool(val & 0b00010000)

    @property
    def BC(self) -> int:
        """
        >>> cpu = CPU()
        >>> cpu.BC = 0x1234
        >>> cpu.B, cpu.C
        (18, 52)

        >>> cpu.B, cpu.C = 1, 2
        >>> cpu.BC
        258
        """
        return self.B << 8 | self.C

    @BC.setter
    def BC(self, val: int) -> None:
        self.B = val >> 8 & 0xFF
        self.C = val & 0xFF

    @property
    def DE(self) -> int:
        """
        >>> cpu = CPU()
        >>> cpu.DE = 0x1234
        >>> cpu.D, cpu.E
        (18, 52)

        >>> cpu.D, cpu.E = 1, 2
        >>> cpu.DE
        258
        """
        return self.D << 8 | self.E

    @DE.setter
    def DE(self, val: int) -> None:
        self.D = val >> 8 & 0xFF
        self.E = val & 0xFF

    @property
    def HL(self) -> int:
        """
        >>> cpu = CPU()
        >>> cpu.HL = 0x1234
        >>> cpu.H, cpu.L
        (18, 52)

        >>> cpu.H, cpu.L = 1, 2
        >>> cpu.HL
        258
        """
        return self.H << 8 | self.L

    @HL.setter
    def HL(self, val: int) -> None:
        self.H = val >> 8 & 0xFF
        self.L = val & 0xFF

    @property
    def MEM_AT_HL(self) -> int:
        return self.ram[self.HL]

    @MEM_AT_HL.setter
    def MEM_AT_HL(self, val: int) -> None:
        self.ram[self.HL] = val

    # </editor-fold>

    # <editor-fold description="Empty Instructions">
    @opcode("ERR CB", 4)
    def opCB(self):
        raise OpNotImplemented("CB is special cased, you shouldn't get here")

    def _err(self, op):
        raise OpNotImplemented(f"Opcode {op} not implemented")

    opD3 = opcode("ERR D3", 4)(lambda self: self._err("D3"))
    opDB = opcode("ERR DB", 4)(lambda self: self._err("DB"))
    opDD = opcode("ERR DD", 4)(lambda self: self._err("DD"))
    opE3 = opcode("ERR E3", 4)(lambda self: self._err("E3"))
    opE4 = opcode("ERR E4", 4)(lambda self: self._err("E4"))
    opEB = opcode("ERR EB", 4)(lambda self: self._err("EB"))
    opEC = opcode("ERR EC", 4)(lambda self: self._err("EC"))
    opED = opcode("ERR ED", 4)(lambda self: self._err("ED"))
    opF4 = opcode("ERR F4", 4)(lambda self: self._err("F4"))
    # opFC = opcode("ERR FC", 4)(lambda self: self._err("FC"))
    # opFD = opcode("ERR FD", 4)(lambda self: self._err("FD"))

    @opcode("EXIT 0", 4)
    def opFC(self):
        raise UnitTestPassed()

    @opcode("EXIT 1", 4)
    def opFD(self):
        raise UnitTestFailed()

    # </editor-fold>

    # <editor-fold description="3.3.1 8-Bit Loads">
    # ===================================
    # 1. LD nn,n
    for base, reg_to in enumerate(GEN_REGS):
        cycles = 12 if "[HL]" in {reg_to} else 8
        op = 0x06 + base * 8
        reg_to_name = reg_to.replace("[HL]", "MEM_AT_HL")
        exec(
            dedent(
                f"""
            @opcode("LD {reg_to},n", {cycles}, "B")
            def op{op:02X}(self, val):
                self.{reg_to_name} = val
        """
            )
        )

    # ===================================
    # 2. LD r1,r2
    # Put r2 into r1
    for base, reg_to in enumerate(GEN_REGS):
        for offset, reg_from in enumerate(GEN_REGS):
            if reg_from == "[HL]" and reg_to == "[HL]":
                continue

            cycles = 8 if "[HL]" in {reg_from, reg_to} else 4
            op = 0x40 + base * 8 + offset
            reg_to_name = reg_to.replace("[HL]", "MEM_AT_HL")
            reg_from_name = reg_from.replace("[HL]", "MEM_AT_HL")
            exec(
                dedent(
                    f"""
                @opcode("LD {reg_to},{reg_from}", {cycles})
                def op{op:02X}(self):
                    self.{reg_to_name} = self.{reg_from_name}
            """
                )
            )

    # ===================================
    # 3. LD A,n
    # Put n into A
    def _ld_val_to_a(self, val):
        self.A = val

    op0A = opcode("LD A,[BC]", 8)(lambda self: self._ld_val_to_a(self.ram[self.BC]))
    op1A = opcode("LD A,[DE]", 8)(lambda self: self._ld_val_to_a(self.ram[self.DE]))
    opFA = opcode("LD A,[nn]", 16, "H")(
        lambda self, val: self._ld_val_to_a(self.ram[val])
    )

    # ===================================
    # 4. LD [nn],A
    def _ld_a_to_mem(self, val):
        self.ram[val] = self.A

    op02 = opcode("LD [BC],A", 8)(lambda self: self._ld_a_to_mem(self.BC))
    op12 = opcode("LD [DE],A", 8)(lambda self: self._ld_a_to_mem(self.DE))
    opEA = opcode("LD [nn],A", 16, "H")(lambda self, val: self._ld_a_to_mem(val))

    # ===================================
    # 5. LD A,(C)
    @opcode("LD A,[C]", 8)
    def opF2(self):
        self.A = self.ram[0xFF00 + self.C]

    # ===================================
    # 6. LD (C),A
    @opcode("LDH [C],A", 8)
    def opE2(self):
        self.ram[0xFF00 + self.C] = self.A

    # ===================================
    # 7. LD A,[HLD]
    # 8. LD A,[HL-]
    # 9. LDD A,[HL]
    @opcode("LD A,[HL-]", 8)
    def op3A(self):
        self.A = self.ram[self.HL]
        self.HL -= 1

    # ===================================
    # 10. LD [HLD],A
    # 11. LD [HL-],A
    # 12. LDD [HL],A
    @opcode("LD [HL-],A", 8)
    def op32(self):
        self.ram[self.HL] = self.A
        self.HL -= 1

    # ===================================
    # 13. LD A,[HLI]
    # 14. LD A,[HL+]
    # 15. LDI A,[HL]
    @opcode("LD A,[HL+]", 8)
    def op2A(self):
        self.A = self.ram[self.HL]
        self.HL += 1

    # ===================================
    # 16. LD [HLI],A
    # 17. LD [HL+],A
    # 18. LDI [HL],A
    @opcode("LD [HL+],A", 8)
    def op22(self):
        self.ram[self.HL] = self.A
        self.HL += 1

    # ===================================
    # 19. LDH [n],A
    @opcode("LDH [n],A", 12, "B")
    def opE0(self, val):
        if val == 0x01:
            print(chr(self.A), end="")
            # print("0xFF%02X = 0x%02X (%s)" % (val, self.A, chr(self.A)))
            sys.stdout.flush()
        self.ram[0xFF00 + val] = self.A

    # ===================================
    # 20. LDH A,[n]
    @opcode("LDH A,[n]", 12, "B")
    def opF0(self, val):
        self.A = self.ram[0xFF00 + val]

    # </editor-fold>

    # <editor-fold description="3.3.2 16-Bit Loads">
    # ===================================
    # 1. LD n,nn
    def _ld_val_to_reg(self, val, reg: Reg):
        setattr(self, reg.value, val)

    op01 = opcode("LD BC,nn", 12, "H")(
        lambda self, val: self._ld_val_to_reg(val, Reg.BC)
    )
    op11 = opcode("LD DE,nn", 12, "H")(
        lambda self, val: self._ld_val_to_reg(val, Reg.DE)
    )
    op21 = opcode("LD HL,nn", 12, "H")(
        lambda self, val: self._ld_val_to_reg(val, Reg.HL)
    )
    op31 = opcode("LD SP,nn", 12, "H")(
        lambda self, val: self._ld_val_to_reg(val, Reg.SP)
    )

    # ===================================
    # 2. LD SP,HL

    @opcode("LD SP,HL", 8)
    def opF9(self):
        self.SP = self.HL

    # ===================================
    # 3. LD HL,SP+n
    # 4. LDHL SP,n
    @opcode("LD HL,SPn", 12, "b")
    def opF8(self, val):
        if val >= 0:
            self.FLAG_C = ((self.SP & 0xFF) + (val & 0xFF)) > 0xFF
            self.FLAG_H = ((self.SP & 0x0F) + (val & 0x0F)) > 0x0F
        else:
            self.FLAG_C = ((self.SP + val) & 0xFF) <= (self.SP & 0xFF)
            self.FLAG_H = ((self.SP + val) & 0x0F) <= (self.SP & 0x0F)
        self.HL = self.SP + val
        self.FLAG_Z = False
        self.FLAG_N = False

    # ===================================
    # 5. LD [nn],SP
    @opcode("LD [nn],SP", 20, "H")
    def op08(self, val):
        self.ram[val + 1] = (self.SP >> 8) & 0xFF
        self.ram[val] = self.SP & 0xFF

    # ===================================
    # 6. PUSH nn
    def _push16(self, reg: Reg):
        """
        >>> c = CPU()
        >>> c.BC = 1234
        >>> c.opC5()
        >>> c.opD1()
        >>> c.DE
        1234
        """
        val = getattr(self, reg.value)
        self.ram[self.SP - 1] = (val & 0xFF00) >> 8
        self.ram[self.SP - 2] = val & 0xFF
        self.SP -= 2
        # print("Pushing %r to stack at %r [%r]" % (val, self.SP, self.ram[-10:]))

    opF5 = opcode("PUSH AF", 16)(lambda self: self._push16(Reg.AF))
    opC5 = opcode("PUSH BC", 16)(lambda self: self._push16(Reg.BC))
    opD5 = opcode("PUSH DE", 16)(lambda self: self._push16(Reg.DE))
    opE5 = opcode("PUSH HL", 16)(lambda self: self._push16(Reg.HL))

    # ===================================
    # 6. POP nn
    def _pop16(self, reg: Reg):
        val = (self.ram[self.SP + 1] << 8) | self.ram[self.SP]
        # print("Set %r to %r from %r, %r" % (reg, val, self.SP, self.ram[-10:]))
        setattr(self, reg.value, val)
        self.SP += 2

    opF1 = opcode("POP AF", 12)(lambda self: self._pop16(Reg.AF))
    opC1 = opcode("POP BC", 12)(lambda self: self._pop16(Reg.BC))
    opD1 = opcode("POP DE", 12)(lambda self: self._pop16(Reg.DE))
    opE1 = opcode("POP HL", 12)(lambda self: self._pop16(Reg.HL))

    # </editor-fold>

    # <editor-fold description="3.3.3 8-Bit Arithmetic">

    # ===================================
    # 1. ADD A,n
    def _add(self, val):
        self.FLAG_C = self.A + val > 0xFF
        self.FLAG_H = (self.A & 0x0F) + (val & 0x0F) > 0x0F
        self.FLAG_N = False
        self.A += val
        self.A &= 0xFF
        self.FLAG_Z = self.A == 0

    op80 = opcode("ADD A,B", 4)(lambda self: self._add(self.B))
    op81 = opcode("ADD A,C", 4)(lambda self: self._add(self.C))
    op82 = opcode("ADD A,D", 4)(lambda self: self._add(self.D))
    op83 = opcode("ADD A,E", 4)(lambda self: self._add(self.E))
    op84 = opcode("ADD A,H", 4)(lambda self: self._add(self.H))
    op85 = opcode("ADD A,L", 4)(lambda self: self._add(self.L))
    op86 = opcode("ADD A,[HL]", 8)(lambda self: self._add(self.MEM_AT_HL))
    op87 = opcode("ADD A,A", 4)(lambda self: self._add(self.A))

    opC6 = opcode("ADD A,n", 8, "B")(lambda self, val: self._add(val))

    # ===================================
    # 2. ADC A,n
    def _adc(self, val):
        """
        >>> c = CPU()
        >>> c.FLAG_C = True
        >>> c.A = 10
        >>> c.B = 5
        >>> c.op88()
        >>> c.A
        16
        """
        carry = int(self.FLAG_C)
        self.FLAG_C = bool(self.A + val + int(self.FLAG_C) > 0xFF)
        self.FLAG_H = (self.A & 0x0F) + (val & 0x0F) + carry > 0x0F
        self.FLAG_N = False
        self.A += val + carry
        self.A &= 0xFF
        self.FLAG_Z = self.A == 0

    op88 = opcode("ADC A,B", 4)(lambda self: self._adc(self.B))
    op89 = opcode("ADC A,C", 4)(lambda self: self._adc(self.C))
    op8A = opcode("ADC A,D", 4)(lambda self: self._adc(self.D))
    op8B = opcode("ADC A,E", 4)(lambda self: self._adc(self.E))
    op8C = opcode("ADC A,H", 4)(lambda self: self._adc(self.H))
    op8D = opcode("ADC A,L", 4)(lambda self: self._adc(self.L))
    op8E = opcode("ADC A,[HL]", 8)(lambda self: self._adc(self.MEM_AT_HL))
    op8F = opcode("ADC A,A", 4)(lambda self: self._adc(self.A))

    opCE = opcode("ADC A,n", 8, "B")(lambda self, val: self._adc(val))

    # ===================================
    # 3. SUB n
    def _sub(self, val):
        self.FLAG_C = self.A < val
        self.FLAG_H = (self.A & 0x0F) < (val & 0x0F)
        self.A -= val
        self.A &= 0xFF
        self.FLAG_Z = self.A == 0
        self.FLAG_N = True

    op90 = opcode("SUB A,B", 4)(lambda self: self._sub(self.B))
    op91 = opcode("SUB A,C", 4)(lambda self: self._sub(self.C))
    op92 = opcode("SUB A,D", 4)(lambda self: self._sub(self.D))
    op93 = opcode("SUB A,E", 4)(lambda self: self._sub(self.E))
    op94 = opcode("SUB A,H", 4)(lambda self: self._sub(self.H))
    op95 = opcode("SUB A,L", 4)(lambda self: self._sub(self.L))
    op96 = opcode("SUB A,[HL]", 8)(lambda self: self._sub(self.MEM_AT_HL))
    op97 = opcode("SUB A,A", 4)(lambda self: self._sub(self.A))

    opD6 = opcode("SUB A,n", 8, "B")(lambda self, val: self._sub(val))

    # ===================================
    # 4. SBC n
    def _sbc(self, val):
        """
        >>> c = CPU()
        >>> c.FLAG_C = True
        >>> c.A = 10
        >>> c.B = 5
        >>> c.op98()
        >>> c.A
        4
        """
        byte1 = self.A
        byte2 = val
        res = byte1 - byte2 - int(self.FLAG_C)
        self._sub(val + int(self.FLAG_C))
        self.FLAG_H = ((byte1 ^ byte2 ^ (res & 0xFF)) & (1 << 4)) != 0

    op98 = opcode("SBC A,B", 4)(lambda self: self._sbc(self.B))
    op99 = opcode("SBC A,C", 4)(lambda self: self._sbc(self.C))
    op9A = opcode("SBC A,D", 4)(lambda self: self._sbc(self.D))
    op9B = opcode("SBC A,E", 4)(lambda self: self._sbc(self.E))
    op9C = opcode("SBC A,H", 4)(lambda self: self._sbc(self.H))
    op9D = opcode("SBC A,L", 4)(lambda self: self._sbc(self.L))
    op9E = opcode("SBC A,[HL]", 8)(lambda self: self._sbc(self.MEM_AT_HL))
    op9F = opcode("SBC A,A", 4)(lambda self: self._sbc(self.A))

    opDE = opcode("SBC A,n", 8, "B")(lambda self, val: self._sbc(val))

    # ===================================
    # 5. AND n
    def _and(self, val):
        """
        >>> c = CPU()
        >>> c.A = 0b0101
        >>> c.B = 0b0011
        >>> c.opA0()
        >>> f"{c.A:04b}"
        '0001'
        """
        self.A &= val
        self.FLAG_Z = int(self.A == 0)
        self.FLAG_N = False
        self.FLAG_H = True
        self.FLAG_C = False

    opA0 = opcode("AND B", 4)(lambda self: self._and(self.B))
    opA1 = opcode("AND C", 4)(lambda self: self._and(self.C))
    opA2 = opcode("AND D", 4)(lambda self: self._and(self.D))
    opA3 = opcode("AND E", 4)(lambda self: self._and(self.E))
    opA4 = opcode("AND H", 4)(lambda self: self._and(self.H))
    opA5 = opcode("AND L", 4)(lambda self: self._and(self.L))
    opA6 = opcode("AND [HL]", 8)(lambda self: self._and(self.MEM_AT_HL))
    opA7 = opcode("AND A", 4)(lambda self: self._and(self.A))

    opE6 = opcode("AND n", 8, "B")(lambda self, n: self._and(n))

    # ===================================
    # 6. OR n
    def _or(self, val):
        """
        >>> c = CPU()
        >>> c.A = 0b0101
        >>> c.B = 0b0011
        >>> c.opB0()
        >>> f"{c.A:04b}"
        '0111'
        """
        self.A |= val
        self.FLAG_Z = int(self.A == 0)
        self.FLAG_N = False
        self.FLAG_H = False
        self.FLAG_C = False

    opB0 = opcode("OR B", 4)(lambda self: self._or(self.B))
    opB1 = opcode("OR C", 4)(lambda self: self._or(self.C))
    opB2 = opcode("OR D", 4)(lambda self: self._or(self.D))
    opB3 = opcode("OR E", 4)(lambda self: self._or(self.E))
    opB4 = opcode("OR H", 4)(lambda self: self._or(self.H))
    opB5 = opcode("OR L", 4)(lambda self: self._or(self.L))
    opB6 = opcode("OR [HL]", 8)(lambda self: self._or(self.MEM_AT_HL))
    opB7 = opcode("OR A", 4)(lambda self: self._or(self.A))

    opF6 = opcode("OR n", 8, "B")(lambda self, n: self._or(n))

    # ===================================
    # 7. XOR
    def _xor(self, val):
        """
        >>> c = CPU()
        >>> c.A = 0b0101
        >>> c.B = 0b0011
        >>> c.opA8()
        >>> f"{c.A:04b}"
        '0110'
        """
        self.A ^= val
        self.FLAG_Z = int(self.A == 0)
        self.FLAG_N = False
        self.FLAG_H = False
        self.FLAG_C = False

    opA8 = opcode("XOR B", 4)(lambda self: self._xor(self.B))
    opA9 = opcode("XOR C", 4)(lambda self: self._xor(self.C))
    opAA = opcode("XOR D", 4)(lambda self: self._xor(self.D))
    opAB = opcode("XOR E", 4)(lambda self: self._xor(self.E))
    opAC = opcode("XOR H", 4)(lambda self: self._xor(self.H))
    opAD = opcode("XOR L", 4)(lambda self: self._xor(self.L))
    opAE = opcode("XOR [HL]", 8)(lambda self: self._xor(self.MEM_AT_HL))
    opAF = opcode("XOR A", 4)(lambda self: self._xor(self.A))

    opEE = opcode("XOR n", 8, "B")(lambda self, n: self._xor(n))

    # ===================================
    # 8. CP
    # Compare A with n
    def _cp(self, n):
        self.FLAG_Z = self.A == n
        self.FLAG_N = True
        self.FLAG_H = (self.A & 0x0F) < (n & 0x0F)
        self.FLAG_C = self.A < n

    opB8 = opcode("CP B", 4)(lambda self: self._cp(self.B))
    opB9 = opcode("CP C", 4)(lambda self: self._cp(self.C))
    opBA = opcode("CP D", 4)(lambda self: self._cp(self.D))
    opBB = opcode("CP E", 4)(lambda self: self._cp(self.E))
    opBC = opcode("CP H", 4)(lambda self: self._cp(self.H))
    opBD = opcode("CP L", 4)(lambda self: self._cp(self.L))
    opBE = opcode("CP [HL]", 8)(lambda self: self._cp(self.MEM_AT_HL))
    opBF = opcode("CP A", 4)(lambda self: self._cp(self.A))

    opFE = opcode("CP n", 8, "B")(lambda self, val: self._cp(val))

    # ===================================
    # 9. INC
    def _inc8(self, reg: Reg):
        val = getattr(self, reg.value)
        self.FLAG_H = val & 0x0F == 0x0F
        val = (val + 1) & 0xFF
        setattr(self, reg.value, val)
        self.FLAG_Z = val == 0
        self.FLAG_N = False

    op04 = opcode("INC B", 4)(lambda self: self._inc8(Reg.B))
    op0C = opcode("INC C", 4)(lambda self: self._inc8(Reg.C))
    op14 = opcode("INC D", 4)(lambda self: self._inc8(Reg.D))
    op1C = opcode("INC E", 4)(lambda self: self._inc8(Reg.E))
    op24 = opcode("INC H", 4)(lambda self: self._inc8(Reg.H))
    op2C = opcode("INC L", 4)(lambda self: self._inc8(Reg.L))
    op34 = opcode("INC [HL]", 12)(lambda self: self._inc8(Reg.MEM_AT_HL))
    op3C = opcode("INC A", 4)(lambda self: self._inc8(Reg.A))

    # ===================================
    # 10. DEC
    def _dec8(self, reg: Reg):
        val = getattr(self, reg.value)
        val = (val - 1) & 0xFF
        self.FLAG_H = val & 0x0F == 0x0F
        setattr(self, reg.value, val)
        self.FLAG_Z = val == 0
        self.FLAG_N = True

    op05 = opcode("DEC B", 4)(lambda self: self._dec8(Reg.B))
    op0D = opcode("DEC C", 4)(lambda self: self._dec8(Reg.C))
    op15 = opcode("DEC D", 4)(lambda self: self._dec8(Reg.D))
    op1D = opcode("DEC E", 4)(lambda self: self._dec8(Reg.E))
    op25 = opcode("DEC H", 4)(lambda self: self._dec8(Reg.H))
    op2D = opcode("DEC L", 4)(lambda self: self._dec8(Reg.L))
    op35 = opcode("DEC [HL]", 12)(lambda self: self._dec8(Reg.MEM_AT_HL))
    op3D = opcode("DEC A", 4)(lambda self: self._dec8(Reg.A))
    # </editor-fold>

    # <editor-fold description="3.3.4 16-Bit Arithmetic">

    # ===================================
    # 1. ADD HL,nn
    def _add_hl(self, val):
        self.FLAG_H = (self.HL & 0x0FFF) + (val & 0x0FFF) > 0x0FFF
        self.FLAG_C = self.HL + val > 0xFFFF
        self.HL += val
        self.HL &= 0xFFFF
        self.FLAG_N = False

    op09 = opcode("ADD HL,BC", 8)(lambda self: self._add_hl(self.BC))
    op19 = opcode("ADD HL,DE", 8)(lambda self: self._add_hl(self.DE))
    op29 = opcode("ADD HL,HL", 8)(lambda self: self._add_hl(self.HL))
    op39 = opcode("ADD HL,SP", 8)(lambda self: self._add_hl(self.SP))

    # ===================================
    # 2. ADD SP,n
    @opcode("ADD SP n", 16, "b")
    def opE8(self, val):
        tmp = self.SP + val
        self.FLAG_H = bool((self.SP ^ val ^ tmp) & 0x10)
        self.FLAG_C = bool((self.SP ^ val ^ tmp) & 0x100)
        self.SP += val
        self.SP &= 0xFFFF
        self.FLAG_Z = False
        self.FLAG_N = False

    # ===================================
    # 3. INC nn
    def _inc16(self, reg):
        val = getattr(self, reg)
        val = (val + 1) & 0xFFFF
        setattr(self, reg, val)

    op03 = opcode("INC BC", 8)(lambda self: self._inc16("BC"))
    op13 = opcode("INC DE", 8)(lambda self: self._inc16("DE"))
    op23 = opcode("INC HL", 8)(lambda self: self._inc16("HL"))
    op33 = opcode("INC SP", 8)(lambda self: self._inc16("SP"))

    # ===================================
    # 4. DEC nn
    def _dec16(self, reg):
        val = getattr(self, reg)
        val = (val - 1) & 0xFFFF
        setattr(self, reg, val)

    op0B = opcode("DEC BC", 8)(lambda self: self._dec16("BC"))
    op1B = opcode("DEC DE", 8)(lambda self: self._dec16("DE"))
    op2B = opcode("DEC HL", 8)(lambda self: self._dec16("HL"))
    op3B = opcode("DEC SP", 8)(lambda self: self._dec16("SP"))

    # </editor-fold>

    # <editor-fold description="3.3.5 Miscellaneous">
    # ===================================
    # 1. SWAP
    # FIXME: CB36 takes 16 cycles, not 8
    def _swap(self, reg: Reg):
        val = getattr(self, reg.value)
        val = ((val & 0xF0) >> 4) | ((val & 0x0F) << 4)
        setattr(self, reg.value, val)
        self.FLAG_Z = val == 0
        self.FLAG_N = False
        self.FLAG_H = False
        self.FLAG_C = False

    # ===================================
    # 2. DAA
    # A = Binary Coded Decimal of A
    @opcode("DAA", 4)
    def op27(self):
        """
        >>> c = CPU()
        >>> c.A = 92
        >>> c.op27()
        >>> bin(c.A)
        '0b11000010'
        """
        tmp = self.A

        if self.FLAG_N == 0:
            if self.FLAG_H or (tmp & 0x0F) > 9:
                tmp += 6
            if self.FLAG_C or tmp > 0x9F:
                tmp += 0x60
        else:
            if self.FLAG_H:
                tmp -= 6
                if self.FLAG_C == 0:
                    tmp &= 0xFF

            if self.FLAG_C:
                tmp -= 0x60

        self.FLAG_H = False
        self.FLAG_Z = False
        if tmp & 0x100:
            self.FLAG_C = True
        self.A = tmp & 0xFF
        if self.A == 0:
            self.FLAG_Z = True

    # ===================================
    # 3. CPL
    # Flip all bits in A
    @opcode("CPL", 4)
    def op2F(self):
        """
        >>> c = CPU()
        >>> c.A = 0b10101010
        >>> c.op2F()
        >>> bin(c.A)
        '0b1010101'
        """
        self.A ^= 0xFF
        self.FLAG_N = True
        self.FLAG_H = True

    # ===================================
    # 4. CCF
    @opcode("CCF", 4)
    def op3F(self):
        """
        >>> c = CPU()
        >>> c.FLAG_C = False
        >>> c.op3F()
        >>> c.FLAG_C
        True
        >>> c.op3F()
        >>> c.FLAG_C
        False
        """
        self.FLAG_N = False
        self.FLAG_H = False
        self.FLAG_C = not self.FLAG_C

    # ===================================
    # 5. SCF
    @opcode("SCF", 4)
    def op37(self):
        """
        >>> c = CPU()
        >>> c.FLAG_C = False
        >>> c.op37()
        >>> c.FLAG_C
        True
        """
        self.FLAG_N = False
        self.FLAG_H = False
        self.FLAG_C = True

    # ===================================
    # 6. NOP
    @opcode("NOP", 4)
    def op00(self):
        pass

    # ===================================
    # 7. HALT
    # Power down CPU until interrupt occurs

    @opcode("HALT", 4)
    def op76(self):
        self.halt = True
        # FIXME: weird instruction skipping behaviour when interrupts are disabled

    # ===================================
    # 8. STOP
    # Halt CPU & LCD until button pressed

    @opcode("STOP", 4, "B")
    def op10(self, sub):  # 10 00
        if sub == 00:
            self.stop = True
        else:
            raise OpNotImplemented("Missing sub-command 10:%02X" % sub)

    # ===================================
    # 9. DI
    @opcode("DI", 4)
    def opF3(self):
        # FIXME: supposed to take effect after the following instruction
        self.interrupts = False

    # ===================================
    # 10. EI
    @opcode("EI", 4)
    def opFB(self):
        # FIXME: supposed to take effect after the following instruction
        self.interrupts = True

    # </editor-fold>

    # <editor-fold description="3.3.6 Rotates & Shifts">
    for base, ins in enumerate(["RLC", "RRC", "RL", "RR", "SLA", "SRA", "SWAP", "SRL"]):
        for offset, reg in enumerate(GEN_REGS):
            op = (base * 8) + offset
            time = 16 if reg == "[HL]" else 8
            regn = reg.replace("[HL]", "MEM_AT_HL")
            exec(
                dedent(
                    f"""
                @opcode("{ins} {reg}", {time})
                def opCB{op:02X}(self):
                    self._{ins.lower()}(Reg.{regn})
            """
                )
            )

    # ===================================
    # 1. RCLA
    @opcode("RCLA", 4)
    def op07(self):
        """
        >>> c = CPU()
        >>> c.A = 0b10101010
        >>> c.FLAG_C = False
        >>> c.op07()
        >>> bin(c.A), c.FLAG_C
        ('0b1010100', True)
        """
        self.FLAG_C = (self.A & 0b10000000) != 0
        self.A = ((self.A << 1) | (self.A >> 7)) & 0xFF
        self.FLAG_Z = False
        self.FLAG_N = False
        self.FLAG_H = False

    # ===================================
    # 2. RLA
    @opcode("RLA", 4)
    def op17(self):
        """
        >>> c = CPU()
        >>> c.A = 0b10101010
        >>> c.FLAG_C = True
        >>> c.op17()
        >>> bin(c.A), c.FLAG_C
        ('0b1010101', True)
        """
        old_c = self.FLAG_C
        self.FLAG_C = (self.A & 0b10000000) != 0
        self.A = ((self.A << 1) | old_c) & 0xFF
        self.FLAG_Z = False
        self.FLAG_N = False
        self.FLAG_H = False

    # ===================================
    # 3. RRCA
    @opcode("RRCA", 4)
    def op0F(self):
        """
        >>> c = CPU()
        >>> c.A = 0b10101010
        >>> c.FLAG_C = True
        >>> c.op0F()
        >>> bin(c.A), c.FLAG_C
        ('0b1010101', False)
        """
        self.FLAG_C = (self.A & 0b00000001) != 0
        self.A = ((self.A >> 1) | (self.A << 7)) & 0xFF
        self.FLAG_Z = False
        self.FLAG_N = False
        self.FLAG_H = False

    # ===================================
    # 4. RRA
    @opcode("RRA", 4)
    def op1F(self):
        """
        >>> c = CPU()
        >>> c.A = 0b10101010
        >>> c.FLAG_C = True
        >>> c.op1F()
        >>> bin(c.A), c.FLAG_C
        ('0b11010101', False)
        """
        old_c = self.FLAG_C
        self.FLAG_C = (self.A & 0b00000001) != 0
        self.A = (self.A >> 1) | (old_c << 7)
        self.FLAG_N = False
        self.FLAG_H = False
        self.FLAG_Z = False

    # ===================================
    # 5. RLC
    def _rlc(self, reg: Reg):
        val = getattr(self, reg.value)
        self.FLAG_C = bool(val & 0b10000000)
        val <<= 1
        if self.FLAG_C:
            val |= 1
        val &= 0xFF
        setattr(self, reg.value, val)
        self.FLAG_N = False
        self.FLAG_H = False
        self.FLAG_Z = val == 0

    # ===================================
    # 6. RL
    def _rl(self, reg: Reg):
        """
        >>> c = CPU()
        >>> c.A = 0xAA
        >>> c.FLAG_C = True

        >>> c._rl(Reg.A)
        >>> hex(c.A), c.FLAG_C
        ('0x55', True)
        >>> c._rl(Reg.A)
        >>> hex(c.A), c.FLAG_C
        ('0xab', False)
        >>> c._rl(Reg.A)
        >>> hex(c.A), c.FLAG_C
        ('0x56', True)
        >>> c._rl(Reg.A)
        >>> hex(c.A), c.FLAG_C
        ('0xad', False)
        """
        orig_c = self.FLAG_C
        val = getattr(self, reg.value)
        self.FLAG_C = bool(val & 0b10000000)
        val = ((val << 1) | orig_c) & 0xFF
        setattr(self, reg.value, val)
        self.FLAG_N = False
        self.FLAG_H = False
        self.FLAG_Z = val == 0

    # ===================================
    # 7. RRC
    def _rrc(self, reg: Reg):
        val = getattr(self, reg.value)
        self.FLAG_C = bool(val & 0x1)
        val >>= 1
        if self.FLAG_C:
            val |= 0b10000000
        setattr(self, reg.value, val)
        self.FLAG_N = False
        self.FLAG_H = False
        self.FLAG_Z = val == 0

    # ===================================
    # 8. RR
    def _rr(self, reg: Reg):
        orig_c = self.FLAG_C
        val = getattr(self, reg.value)
        self.FLAG_C = bool(val & 0x1)
        val >>= 1
        if orig_c:
            val |= 1 << 7
        setattr(self, reg.value, val)
        self.FLAG_N = False
        self.FLAG_H = False
        self.FLAG_Z = val == 0

    # ===================================
    # 9. SLA
    def _sla(self, reg: Reg):
        val = getattr(self, reg.value)
        self.FLAG_C = bool(val & 0b10000000)
        val <<= 1
        val &= 0xFF
        setattr(self, reg.value, val)
        self.FLAG_N = False
        self.FLAG_H = False
        self.FLAG_Z = val == 0

    # ===================================
    # 10. SRA
    def _sra(self, reg: Reg):
        val = getattr(self, reg.value)
        self.FLAG_C = bool(val & 0x1)
        val >>= 1
        if val & 0b01000000:
            val |= 0b10000000
        setattr(self, reg.value, val)
        self.FLAG_N = False
        self.FLAG_H = False
        self.FLAG_Z = val == 0

    # ===================================
    # 11. SRL
    def _srl(self, reg: Reg):
        val = getattr(self, reg.value)
        self.FLAG_C = bool(val & 0x1)
        val >>= 1
        setattr(self, reg.value, val)
        self.FLAG_N = False
        self.FLAG_H = False
        self.FLAG_Z = val == 0

    # </editor-fold>

    # <editor-fold description="3.3.7 Bit Opcodes">
    # ===================================
    # 1. BIT b,r
    def _test_bit(self):
        """
        >>> c = CPU()
        >>> c.B = 0xFF
        >>> c.opCB40()  # BIT 0,B
        >>> c.FLAG_Z
        True
        >>> c.opCB78()  # BIT 7,B
        >>> c.FLAG_Z
        True
        >>> c.B = 0x00
        >>> c.opCB40()
        >>> c.FLAG_Z
        False
        >>> c.opCB78()
        >>> c.FLAG_Z
        False
        """

    for b in range(8):
        for offset, reg in enumerate(GEN_REGS):
            op = 0x40 + b * 0x08 + offset
            time = 16 if reg == "[HL]" else 8
            arg = reg.replace("[HL]", "MEM_AT_HL")
            exec(
                dedent(
                    f"""
                @opcode("BIT {b},{reg}", {time})
                def opCB{op:02X}(self):
                    self.FLAG_Z = not bool(self.{arg} & (1 << {b}))
                    self.FLAG_N = False
                    self.FLAG_H = True
            """
                )
            )

    # ===================================
    # 3. RES b,r
    for b in range(8):
        for offset, arg in enumerate(GEN_REGS):
            op = 0x80 + b * 0x08 + offset
            time = 16 if arg == "[HL]" else 8
            arg = arg.replace("[HL]", "MEM_AT_HL")
            exec(
                dedent(
                    f"""
                @opcode("RES {b},{arg}", {time})
                def opCB{op:02X}(self):
                    self.{arg} &= ((0x01 << {b}) ^ 0xFF)
            """
                )
            )

    # ===================================
    # 2. SET b,r
    for b in range(8):
        for offset, arg in enumerate(GEN_REGS):
            op = 0xC0 + b * 0x08 + offset
            time = 16 if arg == "[HL]" else 8
            arg = arg.replace("[HL]", "MEM_AT_HL")
            exec(
                dedent(
                    f"""
                @opcode("SET {b},{arg}", {time})
                def opCB{op:02X}(self):
                    self.{arg} |= (0x01 << {b})
            """
                )
            )

    # </editor-fold>

    # <editor-fold description="3.3.8 Jumps">
    # ===================================
    # 1. JP nn
    @opcode("JP nn", 16, "H")  # doc says 12
    def opC3(self, nn):
        self.PC = nn

    # ===================================
    # 2. JP cc,nn
    # Absolute jump if given flag is not set / set
    @opcode("JP NZ,nn", 12, "H")
    def opC2(self, n):
        if not self.FLAG_Z:
            self.PC = n

    @opcode("JP Z,nn", 12, "H")
    def opCA(self, n):
        if self.FLAG_Z:
            self.PC = n

    @opcode("JP NC,nn", 12, "H")
    def opD2(self, n):
        if not self.FLAG_C:
            self.PC = n

    @opcode("JP C,nn", 12, "H")
    def opDA(self, n):
        if self.FLAG_C:
            self.PC = n

    # ===================================
    # 3. JP [HL]
    @opcode("JP HL", 4)
    def opE9(self):
        # ERROR: docs say this is [HL], not HL...
        self.PC = self.HL

    # ===================================
    # 4. JR n
    @opcode("JR n", 12, "b")  # doc says 8
    def op18(self, n):
        self.PC += n

    # ===================================
    # 5. JR cc,n
    # Relative jump if given flag is not set / set
    @opcode("JR NZ,n", 8, "b")
    def op20(self, n):
        if not self.FLAG_Z:
            self.PC += n

    @opcode("JR Z,n", 8, "b")
    def op28(self, n):
        if self.FLAG_Z:
            self.PC += n

    @opcode("JR NC,n", 8, "b")
    def op30(self, n):
        if not self.FLAG_C:
            self.PC += n

    @opcode("JR C,n", 8, "b")
    def op38(self, n):
        if self.FLAG_C:
            self.PC += n

    # </editor-fold>

    # <editor-fold description="3.3.9 Calls">
    # ===================================
    # 1. CALL nn
    @opcode("CALL nn", 24, "H")  # doc says 12
    def opCD(self, nn):
        self._push16(Reg.PC)
        self.PC = nn

    # ===================================
    # 2. CALL cc,nn
    # Absolute call if given flag is not set / set
    @opcode("CALL NZ,nn", 12, "H")
    def opC4(self, n):
        if not self.FLAG_Z:
            self._push16(Reg.PC)
            self.PC = n

    @opcode("CALL Z,nn", 12, "H")
    def opCC(self, n):
        if self.FLAG_Z:
            self._push16(Reg.PC)
            self.PC = n

    @opcode("CALL NC,nn", 12, "H")
    def opD4(self, n):
        if not self.FLAG_C:
            self._push16(Reg.PC)
            self.PC = n

    @opcode("CALL C,nn", 12, "H")
    def opDC(self, n):
        if self.FLAG_C:
            self._push16(Reg.PC)
            self.PC = n

    # </editor-fold>

    # <editor-fold description="3.3.10 Restarts">
    # ===================================
    # 1. RST n
    # Push present address onto stack.
    # Jump to address $0000 + n.
    # n = $00,$08,$10,$18,$20,$28,$30,$38
    def _rst(self, val):
        self._push16(Reg.PC)
        self.PC = val

    # doc says 32 cycles, test says 16
    opC7 = opcode("RST 00", 16)(lambda self: self._rst(0x00))
    opCF = opcode("RST 08", 16)(lambda self: self._rst(0x08))
    opD7 = opcode("RST 10", 16)(lambda self: self._rst(0x10))
    opDF = opcode("RST 18", 16)(lambda self: self._rst(0x18))
    opE7 = opcode("RST 20", 16)(lambda self: self._rst(0x20))
    opEF = opcode("RST 28", 16)(lambda self: self._rst(0x28))
    opF7 = opcode("RST 30", 16)(lambda self: self._rst(0x30))
    opFF = opcode("RST 38", 16)(lambda self: self._rst(0x38))
    # </editor-fold>

    # <editor-fold description="3.3.11 Returns">

    # ===================================
    # 1. RET
    @opcode("RET", 16)  # doc says 8
    def opC9(self):
        self._pop16(Reg.PC)

    # ===================================
    # 2. RET cc
    @opcode("RET NZ", 8)
    def opC0(self):
        if not self.FLAG_Z:
            self._pop16(Reg.PC)

    @opcode("RET Z", 8)
    def opC8(self):
        if self.FLAG_Z:
            self._pop16(Reg.PC)

    @opcode("RET NC", 8)
    def opD0(self):
        if not self.FLAG_C:
            self._pop16(Reg.PC)

    @opcode("RET C", 8)
    def opD8(self):
        if self.FLAG_C:
            self._pop16(Reg.PC)

    # ===================================
    # 3. RETI
    @opcode("RETI", 16)  # doc says 8
    def opD9(self):
        self._pop16(Reg.PC)
        self.interrupts = True

    # </editor-fold>
