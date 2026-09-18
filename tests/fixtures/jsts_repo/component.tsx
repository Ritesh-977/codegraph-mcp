import { authenticate } from "./auth";

// Modern style: arrow consts + default export. The original fixture only had
// classic `function` declarations, which is how the arrow-function gap went
// unnoticed until Phase 4.
const useSession = () => {
  return authenticate("admin");
};

export const Panel = () => {
  const refresh = () => {
    useSession();
  };
  refresh();
};

export default () => {
  Panel();
};
