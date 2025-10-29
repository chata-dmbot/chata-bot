export type MobileNavItemProps = {
  text: string;
  hasIcon?: boolean;
  hasEndElement?: boolean;
};

export const MobileNavItem = (props: MobileNavItemProps) => {
  return (
    <div className="relative items-center box-border caret-transparent flex min-h-[auto] min-w-[auto] py-[15px] md:min-h-0 md:min-w-0">
      {props.hasIcon && (
        <div className="box-border caret-transparent min-h-[auto] min-w-[auto] md:min-h-0 md:min-w-0 bg-white h-5 w-px mr-[18px] mb-0.5 md:h-[15px]"></div>
      )}
      <div className="text-3xl box-border caret-transparent leading-9 min-h-[auto] min-w-[auto] text-nowrap px-5 py-2.5 md:text-xl md:leading-7 md:min-h-0 md:min-w-0">
        {props.text}
      </div>
      {props.hasEndElement && (
        <div className="relative bg-white box-border caret-transparent h-5 min-h-[auto] min-w-[auto] w-px ml-5 mb-0.5 right-0 md:h-[15px] md:min-h-0 md:min-w-0"></div>
      )}
    </div>
  );
};
