# bit masks ketu se normal subset checks jane slow
from __future__ import annotations
from collections.abc import Iterator

#antichain cahce 
# checks around MARCO
# # MARCO result -> minmax frontier -> bitset checks
class BitsetAntichainIndex:
    __slots__ = (
        '_active_slots', "_free_slots",
        "_mask_by_slot", '_slot_by_mask',
        "_universe_mask", "_with_bit",
    )

    def __init__(self, width: int) -> None:
        self._universe_mask=(1 << width)-1; self._active_slots=0
        self._with_bit = [0]*width
        self._mask_by_slot: list[int | None] = []
        self._slot_by_mask:dict[int,int]={};
        self._free_slots: list[int] = [] #use free slots dont increse masks

    def contains_subset(self,mask:int)->bool: return bool(self._subset_slots(mask))

    def contains_superset(self, mask:int)->bool:
        z=self._superset_slots(mask); return bool(z)

    def remove_subsets(self,mask:int)->int:
        slots=self._subset_slots(mask); return self._remove_slots(slots)

    def remove_supersets(self, mask: int) -> int:
        slots = self._superset_slots(mask); out=self._remove_slots(slots)
        return out

    def add(self,mask:int)->bool:
        if (mask in self._slot_by_mask): return False
        if self._free_slots:
            k = self._free_slots.pop()
            self._mask_by_slot[k] = mask
        else:
            k = len(self._mask_by_slot)
            self._mask_by_slot.append(mask)
        b=1 << k; self._active_slots |= b
        self._slot_by_mask[mask]=k
        for i in self._set_bit_indexes(mask):
            self._with_bit[i] |= b
        return (True)

    def _subset_slots(self, mask: int) -> int:
        out=self._active_slots; left=self._universe_mask ^ mask
        while left and out:
            b=(left & -left); out &= ~self._with_bit[b.bit_length()-1]
            left^=b
        return out

    def _superset_slots(self, mask: int) -> int:
        out = self._active_slots
        need=mask # bits still needed
        while need and out:
            b = need & -need
            out &= self._with_bit[b.bit_length() - 1]
            need ^= b
        return out

    def _remove_slots(self, slots: int) -> int: #clear indices before recycle
        n=0;
        while slots:
            b = slots & -slots
            k = b.bit_length() - 1
            m = self._mask_by_slot[k]
            assert m is not None
            for i in self._set_bit_indexes(m):
                self._with_bit[i] &= ~b
            self._active_slots &= ~b; del self._slot_by_mask[m]
            self._mask_by_slot[k] = None
            self._free_slots.append(k)
            n += 1; slots ^= b
        return n

    @staticmethod
    def _set_bit_indexes(mask: int) -> Iterator[int]:
        while mask:
            b = mask & -mask
            yield (b.bit_length() - 1)
            mask ^= b
