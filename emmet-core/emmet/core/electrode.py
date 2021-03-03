from datetime import datetime
from typing import Dict, List, Union

from monty.json import MontyDecoder
from pydantic import BaseModel, Field, validator
from pymatgen.apps.battery.battery_abc import AbstractElectrode
from pymatgen.apps.battery.conversion_battery import ConversionElectrode
from pymatgen.apps.battery.insertion_battery import InsertionElectrode
from pymatgen.core import Composition, Structure
from pymatgen.core.periodic_table import Element
from pymatgen.entries.computed_entries import ComputedEntry

from emmet.core.mpid import MPID
from emmet.core.utils import jsanitize


class VoltagePairDoc(BaseModel):
    """
    Data for individual voltage steps.
    Note: Each voltage step is represented as a sub_electrode (ConversionElectrode/InsertionElectrode)
        object to gain access to some basic statistics about the voltage step
    """

    max_delta_volume: str = Field(
        None,
        description="Volume changes in % for a particular voltage step using: "
        "max(charge, discharge) / min(charge, discharge) - 1",
    )

    average_voltage: float = Field(
        None,
        description="The average voltage in V for a particular voltage step.",
    )

    capacity_grav: float = Field(None, description="Gravimetric capacity in mAh/g.")

    capacity_vol: float = Field(None, description="Volumetric capacity in mAh/cc.")

    energy_grav: float = Field(
        None, description="Gravimetric energy (Specific energy) in Wh/kg."
    )

    energy_vol: float = Field(
        None, description="Volumetric energy (Energy Density) in Wh/l."
    )

    fracA_charge: float = Field(
        None, description="Atomic fraction of the working ion in the charged state."
    )

    fracA_discharge: float = Field(
        None, description="Atomic fraction of the working ion in the discharged state."
    )

    @classmethod
    def from_sub_electrode(cls, sub_electrode: AbstractElectrode, **kwargs):
        """
        Convert A pymatgen electrode object to a document
        """
        return cls(**sub_electrode.get_summary_dict(), **kwargs)


class InsertionVoltagePairDoc(VoltagePairDoc):
    """
    Features specific to insertion electrode
    """

    stability_charge: float = Field(
        None, description="The energy above hull of the charged material."
    )

    stability_discharge: float = Field(
        None, description="The energy above hull of the discharged material."
    )


class InsertionElectrodeDoc(InsertionVoltagePairDoc):
    """
    Insertion electrode
    """

    battery_id: str = Field(None, description="The id for this battery document.")

    framework_formula: str = Field(
        None, description="The id for this battery document."
    )

    host_structure: Structure = Field(
        None,
        description="Host structure (structure without the working ion)",
    )

    adj_pairs: List[InsertionVoltagePairDoc] = Field(
        None,
        description="Returns all the Voltage Steps",
    )

    working_ion: Element = Field(
        None,
        description="The working ion as an Element object",
    )

    num_steps: float = Field(
        None,
        description="The number of distinct voltage steps in from fully charge to "
        "discharge based on the stable intermediate states",
    )

    max_voltage_step: float = Field(
        None, description="Maximum absolute difference in adjacent voltage steps"
    )

    last_updated: datetime = Field(
        None,
        description="Timestamp for the most recent calculation for this Material document",
    )

    framework: Composition

    # Make sure that the datetime field is properly formatted
    @validator("last_updated", pre=True)
    def last_updated_dict_ok(cls, v):
        return MontyDecoder().process_decoded(v)

    @classmethod
    def from_entries(
        cls,
        grouped_entries: List[ComputedEntry],
        working_ion_entry: ComputedEntry,
        task_id: Union[MPID, int],
        host_structure: Structure,
    ) -> Union["InsertionElectrodeDoc", None]:
        try:
            ie = InsertionElectrode.from_entries(
                entries=grouped_entries, working_ion_entry=working_ion_entry
            )
        except IndexError:
            return None
        d = ie.get_summary_dict()
        d["num_steps"] = d.pop("nsteps", None)
        d["last_updated"] = datetime.utcnow()
        return cls(
            task_id=task_id,
            host_structure=host_structure.as_dict(),
            framework=Composition(d["framework_formula"]),
            **d
        )


class ConversionVoltagePairDoc(VoltagePairDoc):
    """
    Features specific to conversion electrode
    """

    reactions: List[str] = Field(
        None,
        description="The reaction(s) the characterizes that particular voltage step.",
    )


class ConversionElectrodeDoc(ConversionVoltagePairDoc):
    battery_id: str = Field(None, description="The id for this battery document.")

    adj_pairs: List[ConversionVoltagePairDoc] = Field(
        None,
        description="Returns all the adjacent Voltage Steps",
    )

    working_ion: Element = Field(
        None,
        description="The working ion as an Element object",
    )

    num_steps: float = Field(
        None,
        description="The number of distinct voltage steps in from fully charge to "
        "discharge based on the stable intermediate states",
    )

    max_voltage_step: float = Field(
        None, description="Maximum absolute difference in adjacent voltage steps"
    )

    last_updated: datetime = Field(
        None,
        description="Timestamp for the most recent calculation for this Material document",
    )

    # Make sure that the datetime field is properly formatted
    @validator("last_updated", pre=True)
    def last_updated_dict_ok(cls, v):
        return MontyDecoder().process_decoded(v)

    @classmethod
    def from_composition_and_entries(
        cls,
        composition: Composition,
        entries: List[ComputedEntry],
        working_ion_symbol: str,
        task_id: Union[MPID, int],
    ):
        ce = ConversionElectrode.from_composition_and_entries(
            comp=composition,
            entries_in_chemsys=entries,
            working_ion_symbol=working_ion_symbol,
        )
        d = ce.get_summary_dict()
        d["num_steps"] = d.pop("nsteps", None)
        d["last_updated"] = datetime.utcnow()
        return cls(task_id=task_id, framework=Composition(d["framework_formula"]), **d)