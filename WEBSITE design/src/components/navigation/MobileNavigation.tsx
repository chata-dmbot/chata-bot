import { MobileMenu } from "@/components/navigation/MobileMenu";

export const MobileNavigation = () => {
  return (
    <div className="fixed items-center box-border caret-transparent flex flex-col h-full justify-center w-full z-[999998] left-0 top-0 md:hidden">
      <MobileMenu />
    </div>
  );
};
