import { NavItem } from "@/components/navigation/NavItem";

export const NavigationMenu = () => {
  return (
    <div className="items-center backdrop-blur-[15px] box-border caret-transparent flex h-full justify-center w-full overflow-hidden">
      <NavItem text="HOME" showIcon={true} showDivider={true} />
      <NavItem text="COLLECTIONS" />
      <NavItem text="F.A.Q" />
      <NavItem text="DATA POINTS" />
    </div>
  );
};
