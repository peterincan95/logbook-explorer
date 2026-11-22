// Flag shown in the popup for each Nationality value (modern flags for now).
// Country flags come from the flag-icons package (square versions, shown as a
// circle); Hamburg's is a simplified drawing in src/assets/flags/.
import gb from "flag-icons/flags/1x1/gb.svg";
import nl from "flag-icons/flags/1x1/nl.svg";
import es from "flag-icons/flags/1x1/es.svg";
import fr from "flag-icons/flags/1x1/fr.svg";
import se from "flag-icons/flags/1x1/se.svg";
import dk from "flag-icons/flags/1x1/dk.svg";
import us from "flag-icons/flags/1x1/us.svg";
import hamburg from "../assets/flags/hamburg.svg";

export const flags = {
  BRITISH: gb,
  DUTCH: nl,
  SPANISH: es,
  FRENCH: fr,
  SWEDISH: se,
  DANISH: dk,
  AMERICAN: us,
  HAMBURG: hamburg,
};
