from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple
import re


@dataclass
class Instruction:
    index: int
    text: str
    line_number: int = 0

    @property
    def opcode(self) -> str:
        s = self.text.strip()

        if not s:
            return ""

        # Label, vi du :cond_1
        if s.startswith(":"):
            return "label"

        return s.split()[0]


@dataclass
class BasicBlock:
    id: int
    start: int
    end: int
    instructions: List[Instruction] = field(default_factory=list)
    successors: Set[int] = field(default_factory=set)
    predecessors: Set[int] = field(default_factory=set)

    def add_successor(self, block_id: int):
        self.successors.add(block_id)

    def add_predecessor(self, block_id: int):
        self.predecessors.add(block_id)


@dataclass
class ControlFlowGraph:
    method: str
    blocks: Dict[int, BasicBlock] = field(default_factory=dict)
    entry: Optional[int] = None
    exits: Set[int] = field(default_factory=set)

    def add_block(self, block: BasicBlock):
        self.blocks[block.id] = block

        if self.entry is None:
            self.entry = block.id

    def connect(self, src: int, dst: int):
        if src not in self.blocks or dst not in self.blocks:
            return

        self.blocks[src].add_successor(dst)
        self.blocks[dst].add_predecessor(src)

    def reachable(self) -> Set[int]:
        if self.entry is None:
            return set()

        seen = set()
        stack = [self.entry]

        while stack:
            current = stack.pop()

            if current in seen:
                continue

            seen.add(current)

            block = self.blocks.get(current)
            if block:
                stack.extend(block.successors)

        return seen


class CFGBuilder:
    """
    Dựng Control-Flow Graph đơn giản cho một method Smali.

    Đây là tầng phân tích, không sửa APK.
    """

    # Cac lệnh nhay co dieu kien
    CONDITIONAL_BRANCHES = {
        "if-eq",
        "if-ne",
        "if-lt",
        "if-ge",
        "if-gt",
        "if-le",
        "if-eqz",
        "if-nez",
        "if-ltz",
        "if-gez",
        "if-gtz",
        "if-lez",
    }

    UNCONDITIONAL_BRANCHES = {
        "goto",
        "goto/16",
        "goto/32",
    }

    TERMINATORS = {
        "return-void",
        "return",
        "return-wide",
        "return-object",
        "throw",
    }

    def __init__(self, method: str = "<unknown>"):
        self.method = method

    def parse_instructions(self, smali: str) -> List[Instruction]:
        result = []

        for source_line, line in enumerate(
            smali.splitlines(),
            start=1
        ):
            text = line.strip()

            if not text:
                continue

            # Bo comment
            if text.startswith("#"):
                continue

            # Directive khong phai instruction
            if text.startswith("."):
                continue

            result.append(
                Instruction(
                    index=len(result),
                    text=text,
                    line_number=source_line
                )
            )

        return result

    def _labels(
        self,
        instructions: List[Instruction]
    ) -> Dict[str, int]:

        labels = {}

        for ins in instructions:
            if ins.text.startswith(":"):
                labels[ins.text.split()[0]] = ins.index

        return labels

    def _branch_target(self, text: str) -> Optional[str]:
        parts = text.split()

        if len(parts) < 2:
            return None

        return parts[-1]

    def _leaders(
        self,
        instructions: List[Instruction],
        labels: Dict[str, int]
    ) -> Set[int]:

        if not instructions:
            return set()

        leaders = {instructions[0].index}

        for ins in instructions:
            opcode = ins.opcode

            if opcode in self.CONDITIONAL_BRANCHES:
                target = self._branch_target(ins.text)

                if target in labels:
                    leaders.add(labels[target])

                if ins.index + 1 < len(instructions):
                    leaders.add(ins.index + 1)

            elif opcode in self.UNCONDITIONAL_BRANCHES:
                target = self._branch_target(ins.text)

                if target in labels:
                    leaders.add(labels[target])

                if ins.index + 1 < len(instructions):
                    leaders.add(ins.index + 1)

            elif opcode in self.TERMINATORS:
                if ins.index + 1 < len(instructions):
                    leaders.add(ins.index + 1)

        return leaders

    def build(self, smali: str) -> ControlFlowGraph:
        instructions = self.parse_instructions(smali)

        cfg = ControlFlowGraph(
            method=self.method
        )

        if not instructions:
            return cfg

        labels = self._labels(instructions)
        leaders = sorted(
            self._leaders(
                instructions,
                labels
            )
        )

        # Tao basic blocks
        for block_id, start in enumerate(leaders):

            next_starts = [
                x for x in leaders
                if x > start
            ]

            if next_starts:
                end = next_starts[0] - 1
            else:
                end = instructions[-1].index

            block_instructions = [
                ins for ins in instructions
                if start <= ins.index <= end
            ]

            block = BasicBlock(
                id=block_id,
                start=start,
                end=end,
                instructions=block_instructions
            )

            cfg.add_block(block)

        # Map instruction index -> block
        instruction_to_block = {}

        for block in cfg.blocks.values():
            for ins in block.instructions:
                instruction_to_block[ins.index] = block.id

        # Ket noi block
        for block in cfg.blocks.values():

            if not block.instructions:
                continue

            last = block.instructions[-1]
            opcode = last.opcode

            if opcode in self.TERMINATORS:
                cfg.exits.add(block.id)
                continue

            if opcode in self.UNCONDITIONAL_BRANCHES:
                target = self._branch_target(last.text)

                if target in labels:
                    target_index = labels[target]
                    dst = instruction_to_block.get(
                        target_index
                    )

                    if dst is not None:
                        cfg.connect(
                            block.id,
                            dst
                        )

                continue

            if opcode in self.CONDITIONAL_BRANCHES:
                target = self._branch_target(last.text)

                if target in labels:
                    target_index = labels[target]
                    dst = instruction_to_block.get(
                        target_index
                    )

                    if dst is not None:
                        cfg.connect(
                            block.id,
                            dst
                        )

                # Nhanh fall-through
                next_block = self._next_block(
                    cfg,
                    block.id
                )

                if next_block is not None:
                    cfg.connect(
                        block.id,
                        next_block
                    )

                continue

            # Instruction binh thuong
            next_block = self._next_block(
                cfg,
                block.id
            )

            if next_block is not None:
                cfg.connect(
                    block.id,
                    next_block
                )
            else:
                cfg.exits.add(block.id)

        return cfg

    @staticmethod
    def _next_block(
        cfg: ControlFlowGraph,
        block_id: int
    ) -> Optional[int]:

        ids = sorted(cfg.blocks)

        try:
            pos = ids.index(block_id)
        except ValueError:
            return None

        if pos + 1 >= len(ids):
            return None

        return ids[pos + 1]


def build_cfg(
    smali: str,
    method: str = "<unknown>"
) -> ControlFlowGraph:

    return CFGBuilder(method).build(smali)
