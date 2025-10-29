export type NavItemProps = {
  text: string;
  showIcon?: boolean;
  showDivider?: boolean;
};

export const NavItem = (props: NavItemProps) => {
  return (
    <div className="relative items-center box-border caret-transparent flex py-[15px] md:py-[5px]">
      {props.showIcon && (
        <div className="box-border caret-transparent bg-white h-5 w-px mr-[18px] mb-0.5 md:h-[15px]"></div>
      )}
      <div className="box-border caret-transparent text-3xl leading-9 text-nowrap pr-5 md:text-xl md:leading-7">
        {props.text}
      </div>
      {props.showDivider && (
        <div className="bg-white box-border caret-transparent h-5 w-px mb-0.5 md:h-[15px]"></div>
      )}
      <div className="absolute bg-transparent box-border caret-transparent h-full w-full left-0 top-0"></div>
    </div>
  );
};
