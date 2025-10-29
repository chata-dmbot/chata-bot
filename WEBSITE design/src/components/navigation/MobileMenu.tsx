import { MobileNavItem } from "@/components/navigation/MobileNavItem";

export const MobileMenu = () => {
  return (
    <div className="relative items-center backdrop-blur-lg bg-white/30 box-border caret-transparent flex flex-col h-full justify-center min-h-[auto] min-w-[auto] opacity-95 w-0 overflow-hidden md:min-h-0 md:min-w-0">
      <MobileNavItem text="HOME" hasIcon={true} hasEndElement={true} />
      <MobileNavItem text="COLLECTIONS" />
      <MobileNavItem text="F.A.Q" />
      <MobileNavItem text="DATA POINTS" />
    </div>
  );
};
