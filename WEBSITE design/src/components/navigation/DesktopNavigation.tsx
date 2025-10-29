import { NavigationMenu } from "@/components/navigation/NavigationMenu";

export const DesktopNavigation = () => {
  return (
    <div className="fixed items-center box-border caret-transparent block justify-center w-full z-[100] left-0 top-0 md:flex">
      <div className="relative box-border caret-transparent max-w-[2094px] min-h-0 min-w-0 w-full md:min-h-[auto] md:min-w-[auto]">
        <div className="absolute items-center box-border caret-transparent flex h-[1000px] justify-center w-full left-0 top-0 md:h-auto">
          <div className="relative items-center box-border caret-transparent flex flex-col h-0 justify-center max-w-[1022px] w-full overflow-hidden px-3 py-[11px] md:h-auto md:p-[22px]">
            <div className="items-end bg-transparent box-border caret-transparent flex flex-col h-full justify-end w-full overflow-hidden md:bg-black/30 md:flex-row">
              <NavigationMenu />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
